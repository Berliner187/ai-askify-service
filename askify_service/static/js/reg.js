function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');


$('#registration-form').on('submit', function(event) {
    event.preventDefault();

    $('#alertContainer').html('').hide();

    $.ajax({
        type: 'POST',
        url: '',
        headers: {
            'X-CSRFToken': csrftoken
        },
        data: $(this).serialize(),
        success: function(response) {
            if (response.redirect) {
                window.location.href = response.redirect;
            } else {
                $('#alertContainer').html('Регистрация прошла успешно.').show();
            }
        },
        error: function(xhr) {
            console.log(xhr.responseText);

            if (xhr.status === 400) {
                const errors = xhr.responseJSON.errors;
                if (errors) {
                    let errorHtml = '<ul class="errorlist">';
                    for (const field in errors) {
                        const $field = $(`#${field}Error`);
                        if ($field.length) {
                            $field.text(errors[field].join(', ')).show();
                        } else {
                            errorHtml += `<li>${field}: ${errors[field].join(', ')}</li>`;
                        }
                    }
                    errorHtml += '</ul>';
                    $('#alertContainer').html(errorHtml).show();
                } else {
                    $('#alertContainer').html('Неизвестная ошибка.').show();
                }
            } else {
                $('#alertContainer').html(xhr.responseJSON.message || 'Ошибка сервера').show();
            }
        }
    });
});

