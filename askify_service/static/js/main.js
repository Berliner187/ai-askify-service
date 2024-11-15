const dropArea = document.getElementById('drop-area');

async function submitText() {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]') 
                    ? document.querySelector('[name=csrfmiddlewaretoken]').value
                    : document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    const text = document.getElementById('user-text').value;
    const blockGenerate = document.getElementById('block-generate');
    const loadingIndicator = document.getElementById('loading-container');

    if (validatorText(text)) {
        console.log('Text validation failed');
        return;
    }

    loadingIndicator.style.display = 'block';
    blockGenerate.style.opacity = 0;
    dropArea.style.opacity = 0;

    try {
        console.log('Sending text:', text);
        console.log('Object to send:', { text });

        const response = await fetch('/api-create-survey/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({ text }),
        });

        console.log('Response status:', response.status);
        const result = await response.json();

        if (response.ok) {
            console.log("Response -", 200);
            window.location.href = `/history/`;
            console.log(result);
        } else {
            console.error('Error:', result);
            alert(result.error || 'Не удалось выполнить запрос');
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Произошла ошибка при отправке запроса: ' + error.message);
    } finally {
        loadingIndicator.style.display = 'none';
        blockGenerate.style.opacity = 1;
        dropArea.style.opacity = 1;
    }
}

const uploadButton = document.querySelector('.upload-button');
const checkmark = uploadButton.querySelector('.checkmark');
const fileInput = document.getElementById('file-upload');

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
});

['dragenter', 'dragover'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.add('hover'), false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.remove('hover'), false);
});

dropArea.addEventListener('drop', handleDrop, false);
dropArea.addEventListener('click', () => fileInput.click());

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    handleFiles(files);
}

fileInput.addEventListener('change', function(event) {
    const file = fileInput.files[0];
    if (file) {
        handleFiles([file]);
    } else {
        alert('Пожалуйста, выберите файл для загрузки.');
    }
});


async function handleFiles(files) {
    const file = files[0];
    if (file) {
        uploadButton.style.display = 'inline-block';
        uploadButton.classList.add('loading');
        checkmark.style.display = 'block';

        const formData = new FormData();
        formData.append('file', file);

        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]') 
        ? document.querySelector('[name=csrfmiddlewaretoken]').value
        : document.querySelector('meta[name="csrf-token"]').getAttribute('content');

        try {
            const response = await fetch('/upload/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': csrftoken
                }
            });
        
            if (response.ok) {
                console.log('Файл успешно загружен');
                window.location.href = `/history/`;
            } else {
                console.error('Ошибка при загрузке файла:', response.statusText);
                alert('Не удалось загрузить файл: ' + response.statusText);
            }        
        } catch (error) {
            console.error('Ошибка:', error);
            alert('Произошла ошибка при отправке запроса: ' + error.message);
        } finally {
            setTimeout(() => {
                uploadButton.classList.remove('loading');
                uploadButton.classList.remove('loading');
                checkmark.style.display = 'none';
            }, 2000);
        }
    } else {
        alert('Пожалуйста, выберите файл для загрузки.');
    }
}


async function submitTextWithFile(data) {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]') 
                    ? document.querySelector('[name=csrfmiddlewaretoken]').value
                    : document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    const text = document.getElementById('user-text').value;
    const blockGenerate = document.getElementById('block-generate');
    const loadingIndicator = document.getElementById('loading-container');

    loadingIndicator.style.display = 'block';
    blockGenerate.style.opacity = 0.3;

    try {
        console.log('Sending text and file data:', text, data);
        console.log('Object to send:', { text, fileData: data });

        const response = await fetch('/api-create-survey/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({ text, fileData: data }),
        });

        console.log('Response status:', response.status);
        const result = await response.json();

        if (response.ok) {
            console.log("Response -", 200);
            window.location.href = `/history/`;
            console.log(result);
        } else {
            console.error('Error:', result);
            alert(result.error || 'Не удалось выполнить запрос');
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Произошла ошибка при отправке запроса: ' + error.message);
    } finally {
        loadingIndicator.style.display = 'none';
        blockGenerate.style.opacity = 1;
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
    else if (text_request.length > 150000) {
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
