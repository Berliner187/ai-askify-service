async function submitText() {
    const text = document.getElementById('user-text').value;
    const blockGeneratedTests = document.getElementById('generated-tests');
    const blockGenerate = document.getElementById('block-generate');
    const loadingIndicator = document.getElementById('loading-container');

    if (validatorText(text)) {
        console.log('ok');
        return;
    }

    // Показать индикатор загрузки
    loadingIndicator.style.display = 'block';
    // blockGeneratedTests.style.display = 'none';
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
            window.location.href = '/history/';
            // blockGeneratedTests.style.display = 'block';
            // window.location.reload();
            console.log(result);
        } else {
            console.error('Error:', result);
            alert(result.error);
            // showError('Неверный запрос');
        }
        blockGenerate.style.opacity = 1;
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Произошла ошибка при отправке запроса: ' + error.message);
    } finally {
        loadingIndicator.style.display = 'none';
    }
}


function showError(message) {
    const errorMessage = document.createElement('div');
    errorMessage.className = 'error-message';
    errorMessage.innerText = message;

    document.body.appendChild(errorMessage);

    errorMessage.style.display = 'block';

    setTimeout(() => {
        errorMessage.style.display = 'none';
        document.body.removeChild(errorMessage);
    }, 5000);
}


function validatorText(text_request) {
    const errors = [];

    text_request = text_request.trim();

    if (text_request === '') {
        errors.push('Запрос не может быть пустым!');
    }
    else if (text_request.length < 10) {
        errors.push('Очень короткий запрос :(');
    }
    else if (text_request.length > 128000) {
        errors.push('Очень длинный запрос :(');
    }
    else if (containsHTMLTags(text_request)) {
        errors.push('Запрос не должен содержать HTML-теги!');
    }

    if (errors.length > 0) {
        alert(errors.join('\n'));
        return true;
    }

    return false;
}

function containsHTMLTags(text) {
    const regex = /<\/?[^>]+(>|$)/;
    return regex.test(text);
}
