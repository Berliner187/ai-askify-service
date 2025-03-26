
// Управление бургер-меню
const burger = document.getElementById('burger');
const navLinks = document.querySelector('.nav-links');

burger.addEventListener('click', () => {
    navLinks.classList.toggle('active');
    burger.classList.toggle('active');
});


let popupTimer;

// Управление верхним попапом
const showPopup = () => {
  const popup = document.querySelector('.popup-overlay');
  popup.classList.add('active');
  
  popupTimer = setTimeout(() => {
    popup.classList.remove('active');
  }, 7000);
};

setTimeout(showPopup, 25000);


// Закрытие попапа при клике на крестик или вне зоны попапа
document.getElementById('popupClose').addEventListener('click', () => {
    document.querySelector('.popup-overlay').classList.remove('active');
});

document.querySelector('.popup-overlay').addEventListener('click', (e) => {
    if (e.target === document.querySelector('.popup-overlay')) {
        document.querySelector('.popup-overlay').classList.remove('active');
    }
});


// Закрытие попапа при клике на ссылку
document.querySelectorAll('a[href*="#pricing"]').forEach(link => {
    link.addEventListener('click', () => {
        document.querySelector('.popup-overlay').classList.remove('active');
    });
});

window.addEventListener('load', function () {
    const preloader = document.querySelector('.preloader');
    preloader.classList.add('fade-out');

    setTimeout(() => {
        preloader.remove();
    }, 300);
});


// Плавная прокрутка для всех якорных ссылок
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const targetId = this.getAttribute('href');
        const targetElement = document.querySelector(targetId);

        if (targetElement) {
            targetElement.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});


// Попап внизу
document.addEventListener('DOMContentLoaded', function() {
    const ltkPopup = document.querySelector('.ltk-popup-overlay');
    const ltkCloseButton = document.querySelector('.ltk-popup-close');

    ltkCloseButton.addEventListener('click', function() {
        ltkPopup.style.display = 'none';
    });

    setTimeout(() => {
        ltkPopup.style.display = 'block';

        setTimeout(() => {
            ltkPopup.style.display = 'none';
        }, 5000);
    }, 12000);
});
