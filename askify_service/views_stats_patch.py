"""
ЗАМЕНА двух вьюх в views.py: personal_charts_data_api и student_charts_data_api.
Рядом положи stats_periods.py (тот же пакет приложения).

Что изменилось:
  * оба эндпоинта принимают ?period=7|30|90|180|365|all (по умолчанию 7);
  * без премиума период принудительно 7 — защита на сервере, а не только на фронте;
  * график режется на корзины (дни / недели / месяцы / годы), в ответе labels + titles + starts + meta;
  * оценки, часы и топ тестов тоже считаются за выбранный период;
  * «из чего состоят тесты» (длина, тип вопросов) — по-прежнему по ВСЕМ тестам;
  * personal-вьюха теперь считает «сегодня» по Москве, как и student-вьюха
    (раньше у неё было UTC и графики могли расходиться на границе суток).

"""


def _stats_first_activity_date(staff_id):
    """Дата самой первой активности юзера (тест / прохождение / просмотр) — для периода «всё время»."""
    first = [
        Survey.objects.filter(id_staff=staff_id).aggregate(m=Min("created_at"))["m"],
        TestAttempt.objects.filter(survey__id_staff=staff_id).aggregate(m=Min("created_at"))["m"],
        SurveyUniqueView.objects.filter(survey__id_staff=staff_id).aggregate(m=Min("timestamp"))["m"],
    ]
    dates = [x.astimezone(MOSCOW_TZ).date() for x in first if x]
    return min(dates) if dates else None


def _stats_context(request, staff_id):
    """period, is_premium, plan — общая «шапка» для обеих вьюх."""
    is_premium = get_subscription_level(request) >= 1
    period = normalize_period(request.GET.get("period"), is_premium)
    today = timezone.now().astimezone(MOSCOW_TZ).date()
    first = _stats_first_activity_date(staff_id) if period == "all" else None
    return period, is_premium, build_plan(period, today, first)


@login_required
def personal_charts_data_api(request):
    """Личная статистика создателя тестов: сколько собрал, сколько просмотров, из чего состоят тесты."""
    timezone.activate(MOSCOW_TZ)
    staff_id = get_staff_id(request)
    period, is_premium, plan = _stats_context(request, staff_id)
    start = plan["start"]

    # Новые тесты по дням
    created = (
        Survey.objects.filter(id_staff=staff_id, created_at__date__gte=start)
        .values("created_at__date").annotate(count=Count("id"))
    )
    activity_map = {r["created_at__date"]: r["count"] for r in created}

    # Уникальные просмотры по дням
    views = (
        SurveyUniqueView.objects.filter(survey__id_staff=staff_id, timestamp__date__gte=start)
        .values("timestamp__date").annotate(count=Count("id"))
    )
    views_map = {r["timestamp__date"]: r["count"] for r in views}

    # Состав тестов — по всем тестам, период не применяется
    all_user_surveys = Survey.objects.filter(id_staff=staff_id)
    quality_distribution = {"Короткие (1-4)": 0, "Оптимальные (5-8)": 0, "Длинные (9+)": 0}
    question_types = {
        "Факты (Что, Кто, Где)": 0,
        "Анализ (Почему, Как)": 0,
        "Классификация (Какой, Выберите)": 0,
        "Прочее": 0,
    }
    keyword_map = {
        "Факты (Что, Кто, Где)": ["что", "кто", "где", "когда", "сколько", "назовите"],
        "Анализ (Почему, Как)": ["почему", "как", "объясните", "сравните"],
        "Классификация (Какой, Выберите)": ["какой", "какая", "какое", "какие", "выберите", "укажите"],
    }
    # Один проход по тестам вместо двух
    for survey in all_user_surveys.only("questions"):
        try:
            questions = survey.get_questions()
        except (json.JSONDecodeError, TypeError):
            continue
        n = len(questions)
        if 1 <= n <= 4:
            quality_distribution["Короткие (1-4)"] += 1
        elif 5 <= n <= 8:
            quality_distribution["Оптимальные (5-8)"] += 1
        else:
            quality_distribution["Длинные (9+)"] += 1
        for q in questions:
            text = (q.get("question", "") if isinstance(q, dict) else "").lower()
            for q_type, kws in keyword_map.items():
                if any(k in text for k in kws):
                    question_types[q_type] += 1
                    break
            else:
                question_types["Прочее"] += 1

    filtered_question_types = {k: v for k, v in question_types.items() if v > 0}

    return JsonResponse({
        "meta": meta_payload(plan, period, is_premium),
        "activity_chart": chart_payload(plan, activity_map),
        "views_chart": chart_payload(plan, views_map),
        "quality_chart": {
            "labels": list(quality_distribution.keys()),
            "data": list(quality_distribution.values()),
        },
        "question_types_chart": {
            "labels": list(filtered_question_types.keys()),
            "data": list(filtered_question_types.values()),
        },
    })


@login_required
def student_charts_data_api(request):
    """Статистика прохождений тестов учениками (Europe/Moscow) за выбранный период."""
    timezone.activate(MOSCOW_TZ)
    staff_id = get_staff_id(request)
    period, is_premium, plan = _stats_context(request, staff_id)
    start = plan["start"]

    user_surveys = Survey.objects.filter(id_staff=staff_id)
    attempts = TestAttempt.objects.filter(survey__in=user_surveys, created_at__date__gte=start)

    # Оценки за период
    pct = ExpressionWrapper((F("score") * 100.0) / F("total_questions"), output_field=FloatField())
    agg = (
        attempts.filter(total_questions__gt=0).annotate(percentage_score=pct)
        .aggregate(
            high=Count("id", filter=Q(percentage_score__gte=80)),
            medium=Count("id", filter=Q(percentage_score__gte=50, percentage_score__lt=80)),
            low=Count("id", filter=Q(percentage_score__lt=50)),
        )
    )
    scores_data = [agg["high"] or 0, agg["medium"] or 0, agg["low"] or 0]

    # Активность по корзинам
    per_day = attempts.values("created_at__date").annotate(count=Count("id"))
    day_map = {r["created_at__date"]: r["count"] for r in per_day}

    # По часам (МСК)
    hourly = (
        attempts.annotate(hour=ExtractHour("created_at", tzinfo=MOSCOW_TZ))
        .values("hour").annotate(count=Count("id"))
    )
    hourly_map = {r["hour"]: r["count"] for r in hourly}

    # Топ тестов за период
    top = (
        attempts.values("survey__title").annotate(attempts_count=Count("id"))
        .order_by("-attempts_count")[:7]
    )

    return JsonResponse({
        "meta": meta_payload(plan, period, is_premium),
        "scores_chart": {
            "labels": ["Отлично (80-100%)", "Хорошо (50-79%)", "Плохо (<50%)"],
            "data": scores_data,
        },
        "attempts_activity_chart": chart_payload(plan, day_map),
        "hourly_activity_chart": {
            "labels": [f"{h:02d}:00" for h in range(24)],
            "data": [hourly_map.get(h, 0) for h in range(24)],
        },
        "survey_engagement_chart": {
            "labels": [t["survey__title"] for t in top],
            "data": [t["attempts_count"] for t in top],
        },
    })