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
            case 'standard':
                price = 220;
                description = 'Стандартный';
                sub_description = 'Доступ на 30 дней за ' + price + ' руб';
                break;
            case 'premium':
                price = 590;
                sub_description = 'Доступ на 30 дней за ' + price + ' руб';
                description = 'Премиум';
                break;
            case 'tokens':
                price = 480;
                sub_description = 'Неограниченный доступ за ' + price + ' руб';
                description = 'Ультра';
                break;
        }

        price_total.textContent = price;
        amountInput.value = price;
        console.log(sub_description);
        descriptionInput.value = description;
        for (i=0; selectedPlanText.length; i++) {
            selectedPlanText[i].textContent = sub_description;
            console.log(selectedPlanText[i].value);
        }
    });
});