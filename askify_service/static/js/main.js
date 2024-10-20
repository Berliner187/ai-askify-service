async function submitText() {
    const text = document.getElementById('user-text').value;
    const blockGeneratedTests = document.getElementById('generated-tests');
    const blockGenerate = document.getElementById('block-generate');
    const loadingIndicator = document.getElementById('loading-container');

    // Показать индикатор загрузки
    loadingIndicator.style.display = 'block';
    blockGeneratedTests.style.display = 'none';
    blockGenerate.style.opacity = 0.3;

    try {
        const response = await fetch('/api-create-survey/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ text }),
        });

        const result = await response.json();
        if (response.ok) {
            console.log("response -", 200);
            blockGeneratedTests.style.display = 'block';
            displaySurvey(result.survey);
        } else {
            console.error('Error: ' + result.error);
        }
        blockGenerate.style.opacity = 1;
    } catch (error) {
        console.error('Ошибка:', error);
    } finally {
        loadingIndicator.style.display = 'none';
    }
}

function displaySurvey(survey) {
    const surveyContainer = document.getElementById('survey-container');
    surveyContainer.innerHTML = '';

    const surveyElement = document.createElement('div');
    surveyElement.innerHTML = survey;
    surveyContainer.appendChild(surveyElement);
}