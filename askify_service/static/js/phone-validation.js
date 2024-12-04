function formatPhoneNumber(input) {
    let value = input.value.replace(/\D/g, '');

    if (value.startsWith('8')) {
        value = '7' + value.slice(1);
    }

    if (value.length > 1) {
        value = '+7 ' + value.slice(1, 4) + ' ' + value.slice(4, 7) + ' ' + value.slice(7, 9) + ' ' + value.slice(9, 11);
    }

    input.value = value.trim();
}
