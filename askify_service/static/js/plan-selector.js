const subscriptionOptions = document.querySelectorAll('.subscription-option');
const amountInput = document.querySelector('input[name="amount"]');
const descriptionInput = document.querySelector('input[name="description"]');
const selectedPlanText = document.querySelectorAll('.selected_plan_text');
const priceElements = document.querySelectorAll('.price');
const price_total = document.getElementById('price_total');

subscriptionOptions.forEach(option => {
    option.addEventListener('click', () => {
        subscriptionOptions.forEach(opt => opt.classList.remove('active'));
        
        option.classList.add('active');

        const selectedPlan = option.getAttribute('data-plan');
        let price, description, sub_description;

        switch (selectedPlan) {
            case 'lite':
                price = 99;
                description = 'Лайтовый';
                sub_description = 'Доступ на 7 дней за ' + price + ' руб';
                break;
            case 'standard':
                price = 320;
                description = 'Стандартный';
                sub_description = 'Доступ на 30 дней за ' + price + ' руб';
                break;
            case 'premium':
                price = 590;
                sub_description = 'Доступ на 30 дней за ' + price + ' руб';
                description = 'Премиум';
                break;
            case 'standard-year':
                price = 2640;
                description = 'Стандартный Год';
                sub_description = 'Доступ на 365 дней за ' + price + ' руб';
                break;
            case 'premium-year':
                price = 4800;
                sub_description = 'Доступ на 365 дней за ' + price + ' руб';
                description = 'Премиум Год';
                break;
            case 'ultra':
                price = 990;
                sub_description = 'Доступ на 30 дней за ' + price + ' руб';
                description = 'Ультра';
                break;
        }

        amountInput.value = price;
        description_order.value = description;
        descriptionInput.value = description;
        for (i=0; selectedPlanText.length; i++) {
            selectedPlanText[i].textContent = description;
        }
    });
});

// Проверка принятия условий для доступа к кнопке оплаты
const checkbox = document.getElementById('agreement');
const submitButton = document.querySelector('.payment-button');

function updateButtonState() {
    if (checkbox.checked) {
        submitButton.disabled = false;
        submitButton.classList.remove('disabled');
    } else {
        submitButton.disabled = true;
        submitButton.classList.add('disabled');
    }
}

checkbox.addEventListener('change', updateButtonState);
updateButtonState();
