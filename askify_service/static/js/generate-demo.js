document.addEventListener('DOMContentLoaded', () => {
    const textInput = document.getElementById('text-input');
    const charCount = document.getElementById('char-count');
    const questionSlider = document.getElementById('question-count');
    const generateBtn = document.getElementById('generate-btn');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // Счетчик символов
    textInput.addEventListener('input', () => {
        charCount.textContent = textInput.value.length;
    });

    // Обновление счетчика вопросов
    questionSlider.addEventListener('input', (e) => {
        document.getElementById('question-count-display').textContent = e.target.value;
    });

    // Обработка генерации
    generateBtn.addEventListener('click', () => {
        handleGeneration();
    });

    class GlassAlert {
        constructor() {
            this.alert = document.getElementById('glass-alert');
            this.messageEl = this.alert.querySelector('.glass-alert__message');
            this.closeBtn = this.alert.querySelector('.glass-alert__close');
            
            this.closeBtn.addEventListener('click', () => this.hide());
            this.hideTimeout = null;
        }
        
        show(message, duration = 5000) {
            clearTimeout(this.hideTimeout);
            this.messageEl.textContent = message;
            this.alert.hidden = false;
            this.alert.classList.remove('hidden');
            this.alert.classList.add('visible');
            
            if (duration) {
            this.hideTimeout = setTimeout(() => {
                this.hide();
            }, duration);
            }
        }
        
        hide() {
            this.alert.classList.remove('visible');
            this.alert.classList.add('hidden');
            this.alert.addEventListener('animationend', () => {
            if (this.alert.classList.contains('hidden')) {
                this.alert.hidden = true;
            }
            }, { once: true });
        }
    }

    const glassAlert = new GlassAlert();

    async function handleGeneration() {

        const text = textInput.value.trim();
        const questions = document.getElementById('question-slider').value;

        if (!text) {
            glassAlert.show('Введите текст для генерации теста');
            return;
        }

        if (text.length < 10) {
            glassAlert.show('Минимальная длина текста - 10 символов');
            return;
        }

        try {
            generateBtn.textContent = generateBtn.getAttribute('data-loading-text');
            toggleLoading(true);
            
            const response = await fetch('/api-non-auth/create-survey/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ 
                    text: text, 
                    questions: questions 
                }),
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Ошибка сервера');
            }

            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error)
            }
            
            if (data.survey_id) {
                loadTests();
                window.location.href = `/c/${data.survey_id}/`;
            } else {
                throw new Error('Неверный формат ответ')
            }
            
        } catch (error) {
            console.error('Ошибка:', error);
            alert(error.message || 'Ошибка генерации');
        } finally {
            await toggleLoading(false);
        }
    }

    async function toggleLoading(isLoading) {
        loadingOverlay.style.display = isLoading ? 'flex' : 'none';
        generateBtn.disabled = isLoading;
        document.body.style.overflow = isLoading ? 'hidden' : 'auto';

        let hint = document.getElementById('loading-hint');

        if (isLoading) {
            if (!hint) {
                hint = document.createElement('div');
                hint.id = 'loading-hint';
                hint.textContent = 'Генерация может занять до 1 минуты...';
                hint.style.cssText = 'margin-top:10px; font-size:14px; color:#888; text-align:center;';
                loadingOverlay.appendChild(hint);
            }
            hint.style.display = 'block';
        } else if (hint) {
            hint.style.display = 'none';
        }
    }

    function getCookie(name) {
        const cookie = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
        return cookie ? cookie.pop() : '';
    }
});

// Функция загрузки тестов
async function loadTests() {
    try {
        const response = await fetch('/api/get-demo-tests/');
        const data = await response.json();

        if (data.tests && data.tests.length > 0) {
            renderTests(data.tests);
        }
    } catch (error) {
        console.error('Ошибка загрузки тестов:', error);
    }
}

// Функция отрисовки тестов
function renderTests(tests) {
    const testGrid = document.getElementById('test-grid');
    testGrid.innerHTML = '';

    tests.forEach((test, index) => {
        const testCard = document.createElement('div');
        testCard.className = 'test-card';
        testCard.style.animationDelay = `${index * 0.15}s`;

        testCard.innerHTML = `
            <div class="test-header">
                <p class="test-title">${test.title || 'Без названия'}</p>
                <div class="copy-wrapper">
                    <button class="neue-btn" data-content="${test.url_link || ''}">
                        <a href="/c/${test.survey_id}/">Открыть</p>
                    </button>
                </div>
            </div>
            <!-- Остальной контент карточки -->
        `;
        
        testGrid.appendChild(testCard);
        
        setTimeout(() => {
            testCard.classList.remove('test-card');
            void testCard.offsetWidth;
            testCard.classList.add('test-card');
        }, 80);
    });
    
    setupCopyButtons();
}


// Настройка кнопок копирования
function setupCopyButtons() {
    const copyButtons = document.querySelectorAll('.copy-btn');
    const notification = document.createElement('div');
    notification.className = 'copy-notification';
    notification.textContent = 'Ссылка скопирована';
    document.body.appendChild(notification);
    
    copyButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const urlToCopy = btn.getAttribute('data-content');

            const protocol = window.location.protocol;
            const host = window.location.host;
            
            let fullLink = protocol + host + urlToCopy;
            copyToClipboard(fullLink);
            
            notification.classList.add('show');
            
            setTimeout(() => {
                notification.classList.remove('show');
            }, 3000);
        });
    });
}

// Функция копирования
function copyToClipboard(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
}

const testGrid = document.getElementById('test-grid');
const resultContainer = document.getElementById('result-container');

if (testGrid.children.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    emptyState.innerHTML = `
        <small>Созданные тесты будут отображаться здесь</small>
    `;
    testGrid.appendChild(emptyState);
}

// setInterval(loadTests, 3000)
document.addEventListener('DOMContentLoaded', loadTests);
