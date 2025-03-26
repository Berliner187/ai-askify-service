document.addEventListener('DOMContentLoaded', function() {
    const target = document.querySelector('.image-text-section');
    let animated = false;

    function animateValue(element, start, end, duration) {
        let startTime = null;
        const step = (timestamp) => {
            if (!startTime) startTime = timestamp;
            const progress = Math.min((timestamp - startTime) / duration, 1);
            element.textContent = Math.floor(progress * (end - start) + start);
            if (progress < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    function handleScroll() {
        const rect = target.getBoundingClientRect();
        if (rect.top <= window.innerHeight * 0.8 && !animated) {
            animated = true;
            
            // Исправленные фильтры
            const totalUsers = {{ total_users|default:16842 }}; 
            const totalYears = {{ total_years|default:9 }};
            
            animateValue(document.getElementById('counter'), 0, totalUsers, 2000);
            animateValue(document.getElementById('years-counter'), 0, totalYears, 2000);
            window.removeEventListener('scroll', handleScroll);
        }
    }

    window.addEventListener('scroll', handleScroll);
    handleScroll();
});