// Управление слайдером
document.addEventListener('DOMContentLoaded', function() {
    const slider = document.getElementById('question-slider');
    const counter = document.getElementById('question-count');

    counter.textContent = slider.value;

    slider.addEventListener('input', function() {
        counter.textContent = this.value;
        
        counter.style.transform = 'scale(1.2)';
        counter.style.color = '#616DF0';
        
        setTimeout(() => {
            counter.style.transform = 'scale(1)';
            counter.style.color = '';
        }, 200);
    });
});


// Управление темами в демо режиме создания тестов
document.addEventListener('DOMContentLoaded', function() {
    const themeData = {
        literature: {
            title: "литературе",
            phrases: [
                "по драматургии Чехова",
                "по лирике Пушкина",
                "по философии Толстого",
                "по символизму в поэзии Блока",
                "по психологизму Достоевского",
            ],
            color: "linear-gradient(45deg, #ff6b6b, #ffa3a3)"
        },
        science: {
            title: "науке",
            phrases: [
                "по квантовой механике",
                "по теории эволюции",
                "по основам генетики",
                "по биохимии клетки",
            ],
            color: "linear-gradient(45deg, #48dbfb, #0abde3)"
        },
        history: {
            title: "истории",
            phrases: [
                "по Древнему Египту",
                "по эпохе Возрождения",
                "по индустриальной революции",
                "по средневековой Европе"
            ],
            color: "linear-gradient(45deg, #feca57, #ff9f43)"
        },
        technology: {
            title: "технологиям",
            phrases: [
                "по искусственному интеллекту",
                "по блокчейн технологиям",
                "по нейросетевым алгоритмам",
                "по квантовым вычислениям"
            ],
            color: "linear-gradient(45deg, #1dd1a1, #10ac84)"
        },
        art: {
            title: "искусству",
            phrases: [
                "по импрессионизму в живописи",
                "по искусству перформанса",
                "по классической опере",
                "по современной скульптуре",
            ],
            color: "linear-gradient(45deg, #9c88ff, #8c7ae6)"
        }
    };

    const themeItems = document.querySelectorAll('.theme-item');
    let currentTheme = 0;
    let typingInterval;
    let currentPhrase = 0;
    let currentLetter = 0;
    let isDeleting = false;

    function typeTheme() {
        const activeTheme = themeItems[currentTheme];
        const typingElement = activeTheme.querySelector('.typing-animation');
        const themeKey = activeTheme.dataset.theme;
        const theme = themeData[themeKey];
        const phrases = theme.phrases;
        
        typingElement.style.background = theme.color;
        typingElement.style.webkitBackgroundClip = 'text';
        typingElement.style.backgroundClip = 'text';
        typingElement.style.webkitTextFillColor = 'transparent';
        
        if (!isDeleting && currentLetter <= phrases[currentPhrase].length) {
            typingElement.textContent = phrases[currentPhrase].substring(0, currentLetter++);
            typingInterval = setTimeout(typeTheme, 60);
        } else if (isDeleting && currentLetter >= 0) {
            typingElement.textContent = phrases[currentPhrase].substring(0, currentLetter--);
            typingInterval = setTimeout(typeTheme, 20);
        } else {
            isDeleting = !isDeleting;
            
            if (!isDeleting) {
                currentPhrase = (currentPhrase + 1) % phrases.length;
            }
            
            typingInterval = setTimeout(typeTheme, isDeleting ? 2000 : 500);
        }
    }

    function changeTheme() {
        themeItems[currentTheme].classList.remove('active');
        clearTimeout(typingInterval);
        
        currentTheme = (currentTheme + 1) % themeItems.length;
        currentPhrase = 0;
        currentLetter = 0;
        isDeleting = false;
        
        setTimeout(() => {
            themeItems[currentTheme].classList.add('active');
            typeTheme();
        }, 500);
    }

    typeTheme();
    
    setInterval(changeTheme, 10000);

    themeItems.forEach(item => {
        item.addEventListener('click', function() {
            const theme = themeData[this.dataset.theme];
            const exampleText = getThemeExample(theme.title);
            document.getElementById('text-input').placeholder = exampleText;
        });
    });

    function getThemeExample(theme) {
        const examples = {
            literature: "Например: В романе 'Преступление и наказание' Достоевский исследует...",
            science: "Например: Квантовая суперпозиция - это явление, при котором...",
            history: "Например: В 1812 году произошло Отечественная война, в ходе которой...",
            technology: "Например: Блокчейн - это цепочка блоков, содержащих...",
            art: "Например: Импрессионисты стремились передать мгновенные впечатления от..."
        };
        return examples[theme] || "Введите текст для генерации теста";
    }
});