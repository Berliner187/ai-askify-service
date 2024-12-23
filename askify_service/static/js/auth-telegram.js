async function submitForm(event) {
    event.preventDefault();

    const form = event.target;
    const formData = new FormData(form);

    try {
        const response = await fetch(form.action, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        console.log(result);

        if (result.status === 'success') {
            if (result.referral_link) {
                document.getElementById('referral-link').innerHTML = 
                    `Перейдите по ссылке ниже для регистрации <a href="${result.referral_link}" target="_blank">${result.referral_code}</a>`;
            } else {
                document.getElementById('code-input').style.display = 'block';
                document.getElementById('phone-input').style.display = 'none';
            }
        } else {
            alert(result.message);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Произошла ошибка при отправке данных.');
    }
}