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
        medicine: {
            title: "медицине",
            phrases: [
                "по фармакологии для аккредитации",
                "по ЭКГ-диагностике за 5 минут",
                "по неотложным состояниям в терапии",
                "по антибиотикотерапии (с ответами)",
                "по сестринскому делу для практики"
            ],
            color: "linear-gradient(45deg, #ff6b6b, #ffa3a3)"
        },
        science: {
            title: "науке",
            phrases: [
               "по методикам преподавания",
                "для подготовки к ЕГЭ",
                "по инклюзивному образованию",
                "по ФГОС нового поколения",
                "по нейропедагогике"
            ],
            color: "linear-gradient(45deg, #48dbfb, #0abde3)"
        },
        it: {
            title: "информационным технологиям",
            phrases: [
                "по программированию на Python",
                "по основам ООП и C++",
                "по веб-разработке и JavaScript",
                "по микроконтроллерам",
                "по информационной безопасности"
            ],
            color: "linear-gradient(45deg, #1dd1a1, #10ac84)"
        },
        education: {
            title: "образованию",
            phrases: [
                "по конспекту лекции за 30 сек",
                "для подготовки к зачету",
                "по учебнику без ручного ввода",
                "с автоматической проверкой",
                "с экспортом в PDF"
            ],
            color: "linear-gradient(45deg, #48dbfb, #0abde3)"
        },
        history: {
            title: "истории",
            phrases: [
                "по технике безопасности",
                "для аттестации сотрудников",
                "по продукту компании",
                "по стандартам ISO",
                "по compliance-требованиям"
            ],
            color: "linear-gradient(45deg, #feca57, #ff9f43)"
        },
        culture: {
            title: "культуре",
            phrases: [
                "для подготовки к ОГЭ/ЕГЭ",
                "по биологии с автопроверкой",
                "по обществознанию (с ответами)",
                "по истории для 10 класса",
                "по химии с разбором ошибок"
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
            typingInterval = setTimeout(typeTheme, 40);
        } else if (isDeleting && currentLetter >= 0) {
            typingElement.textContent = phrases[currentPhrase].substring(0, currentLetter--);
            typingInterval = setTimeout(typeTheme, 10);
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
    
    setInterval(changeTheme, 12000);

});