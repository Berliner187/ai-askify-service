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

    const emailInput = document.getElementById('id_email');
    
    const passwordInput = document.getElementById('id_password1');
    const confirmPasswordInput = document.getElementById('id_password2');
    
    const emailError = document.getElementById('emailError');
    const passwordError = document.getElementById('passwordError');
    const confirmPasswordError = document.getElementById('confirmPasswordError');

    emailInput.addEventListener('input', function() {
        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailPattern.test(emailInput.value)) {
            emailError.textContent = "Введите корректный email.";
            emailError.style.display = 'block';
        } else {
            emailError.style.display = 'none';
        }
    });

    passwordInput.addEventListener('input', function() {
        if (passwordInput.value.length < 6) {
            passwordError.textContent = "Пароль должен содержать минимум 6 символов.";
            passwordError.style.display = 'block';
        } else {
            passwordError.style.display = 'none';
        }
    });

    confirmPasswordInput.addEventListener('input', function() {
        if (confirmPasswordInput.value !== passwordInput.value) {
            confirmPasswordError.textContent = "Пароли не совпадают.";
            confirmPasswordError.style.display = 'block';
        } else {
            confirmPasswordError.style.display = 'none';
        }
    });

    try {
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
    } catch (error) {}

});