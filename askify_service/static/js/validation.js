document.addEventListener('DOMContentLoaded', () => {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach((alert) => {
        alert.classList.add('show');

        setTimeout(() => {
            alert.classList.remove('show');
            setTimeout(() => {
                alert.remove();
            }, 500);
        }, 5000);
    });

    const usernameInput = document.getElementById('username');
    const usernameError = document.getElementById('usernameError');

    usernameInput.addEventListener('input', () => {
        const username = usernameInput.value;
        const usernamePattern = /^[a-z]+$/;

        if (!usernamePattern.test(username)) {
            usernameError.textContent = 'Никнейм должен содержать только строчные латинские буквы без пробелов и спецсимволов.';
            usernameError.style.display = 'block';
        } else {
            usernameError.style.display = 'none';
        }
    });

    const form = document.getElementById('loginForm');
    form.addEventListener('submit', (event) => {
        const username = usernameInput.value;
        if (usernameError.style.display === 'block') {
            event.preventDefault();
        }
    });
});