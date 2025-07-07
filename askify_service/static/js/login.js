function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');

$('#loginForm').on('submit', function(event) {
    event.preventDefault();

    $('#emailError').hide().text('');
    $('#passwordError').hide().text('');

    $.ajax({
        type: 'POST',
        url: window.location.pathname + window.location.search,
        headers: {
            'X-CSRFToken': csrftoken
        },
        data: $(this).serialize(),
        success: function(response) {
            window.location.href = response.redirect || '/create';
        },
        error: function(xhr) {
            if (xhr.status === 400) {
                const errors = xhr.responseJSON.errors;
                if (errors) {
                    if (errors.email) {
                        $('#emailError').text(errors.email.join(', ')).show();
                    }
                    if (errors.password) {
                        $('#passwordError').text(errors.password.join(', ')).show();
                    }
                } else {
                    $('#alertContainer').html('Неизвестная ошибка.').show();
                }
            } else {
                $('#alertContainer').html(xhr.responseJSON.message || 'Ошибка сервера').show();
            }
        }
    });
});