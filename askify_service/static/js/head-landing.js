document.addEventListener('DOMContentLoaded', () => {
    const header = document.getElementById('main-header');
    const burgerBtn = document.getElementById('burger-btn');
    const burgerIcon = document.getElementById('burger-icon');
    const mobileMenu = document.getElementById('mobile-menu');

    if (header) {
        const handleScroll = () => {
            header.classList.toggle('scrolled', window.scrollY > 20);
        };
        window.addEventListener('scroll', handleScroll);
        handleScroll();
    }

    if (burgerBtn && mobileMenu && burgerIcon) {
        burgerBtn.addEventListener('click', () => {
            const isOpened = mobileMenu.classList.toggle('menu-open');
            document.body.style.overflow = isOpened ? 'hidden' : '';
            burgerIcon.classList.toggle('fa-bars', !isOpened);
            burgerIcon.classList.toggle('fa-times', isOpened);
        });
    }
});