const dropArea = document.getElementById('drop-area');

const overlay = document.getElementById('overlay');

async function submitText() {
    const text = document.getElementById('user-text').value.trim();
    const questionCount = document.getElementById('question-slider').value;
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    if (!selectedFile && validatorText(text)) {
        console.log('Text validation failed');
        return;
    }

    document.getElementById('overlay').style.display = 'block';

    try {
        if (selectedFile) {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('question_count', questionCount);

            const response = await fetch('/upload/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken },
                body: formData
            });

            const result = await response.json();
            if (result.success) {
                const surveyId = result.survey_id;
                console.log('Survey ID:', surveyId);

                window.location.href = `/result/` + surveyId;
            } else {
                showToast(result.error || 'Ошибка загрузки файла');
            }
        } else {
            const response = await fetch('/api-create-survey/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: JSON.stringify({ text, questions: questionCount })
            });

            const result = await response.json();
            if (response.ok) {
                window.location.href = `/result/${result.survey_id}`;
            } else {
                showToast(result.error || 'Не удалось создать тест');
            }
        }
    } catch (err) {
        console.error(err);
        showToast('Произошла ошибка');
    } finally {
        document.getElementById('overlay').style.display = 'none';
    }
}


let uploadedFile = null;
let selectedFile = null;


function handleFiles(files) {
    const file = files[0];
    if (!file) return;

    function showSliderBlock(slider, sliderText, count = 5) {
        slider.style.display = 'block';
        sliderText.style.display = 'none';
        slider.parentElement.classList.add('show');
        slider.value = count;
        updateQuestionText(slider.value);
    }

    document.getElementById('remove-file-button').style.display = 'flex';
    document.querySelector('#attached-file-name strong').textContent = file.name;

    // Показ слайдера и текста
    const fileSlider = document.getElementById('question-slider');
    const charCount = document.getElementById('char-count');
    showSliderBlock(fileSlider, charCount);

    selectedFile = file;
    document.getElementById('file-preview-container').style.display = 'block';
    document.querySelector('#attached-file-name strong').textContent = file.name;

    document.getElementById('question-slider').style.display = 'flex';

    updateFilePreview(selectedFile);
    window.letychkaUploadedFile = file;
}


function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function updateFilePreview(file) {
    const previewContainer = document.getElementById('file-preview-container');
    const fileNameEl = previewContainer.querySelector('.file-name strong');
    const fileSizeEl = previewContainer.querySelector('.file-size strong');

    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatBytes(file.size);

    previewContainer.style.display = 'flex';
}



function removeUploadedFile() {
    selectedFile = null;
    window.letychkaUploadedFile = null;
    document.getElementById('hidden-file-input').value = '';
    document.getElementById('file-preview-container').style.display = 'none';
    document.getElementById('char-count').style.display = 'none';
    document.getElementById('question-slider-text').style.display = 'none';
    document.getElementById('remove-file-button').style.display = 'none';
    document.getElementById('question-slider').style.display = 'none';
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
            showToast(result.error || 'Не удалось выполнить запрос');
        }
    } catch (error) {
        console.error('Ошибка:', error);
        showToast('Произошла ошибка при отправке запроса: ' + error.message);
    } finally {
        loadingIndicator.style.display = 'none';
        blockGenerate.style.opacity = 1;
    }
}


function validatorText(text_request) {
    const errors = [];

    text_request = text_request.trim();

    if (text_request === '') {
        errors.push('Запрос не может быть пустым!');
    } else if (text_request.length < 10) {
        errors.push('Очень короткий запрос :(');
    } else if (text_request.length > 150000) {
        errors.push('Очень длинный запрос :(');
    }

    if (errors.length > 0) {
        showToast(errors[0]);
        return true;
    }

    return false;
}


function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    const messageEl = document.getElementById('toast-message');

    messageEl.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.classList.add('hidden'), 1000);
    }, duration);
}


function containsHTMLTags(text) {
    const regex = /<\/?[^>]+(>|$)/;
    return regex.test(text);
}
