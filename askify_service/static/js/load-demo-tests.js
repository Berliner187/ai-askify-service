// Функция загрузки тестов
async function loadTests() {
    try {
        const response = await fetch('/api/get-demo-tests/');
        const data = await response.json();

        console.log(data);
        
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
        // Добавляем задержку для последовательного появления
        testCard.style.animationDelay = `${index * 0.15}s`;
        
        testCard.innerHTML = `
            <div class="test-header">
                <p class="test-title">${test.title || 'Без названия'}</p>
                <div class="copy-wrapper">
                    <button class="copy-btn neue-btn" data-content="${test.url_link || ''}">
                        <i class="fas fa-copy"></i>
                    </button>
                    <a href="${test.url_link}" class="neue-btn open-new-tab" target="_blank">
                        <i class="fas fa-external-link-alt"></i>
                    </a>
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
            const content = btn.getAttribute('data-content');
            copyToClipboard(content);
            
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

//setInterval(loadTests, 1000)

document.addEventListener('DOMContentLoaded', loadTests);
