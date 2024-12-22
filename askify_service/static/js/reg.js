$('#registration-form').on('submit', function(event) {
    event.preventDefault();

    $('#alertContainer').html('').hide();

    $.ajax({
        type: 'POST',
        url: '',
        data: $(this).serialize(),
        success: function(response) {
            if (response.redirect) {
                window.location.href = response.redirect;
            }
        },
        error: function(xhr) {
            console.log(xhr.responseText);
            if (xhr.status === 400) {
                const errors = xhr.responseJSON.errors;
                if (errors) {
                    let errorHtml = '<ul class="errorlist">';
                    let error_message = '';

                    for (const field in errors) {
                        errorHtml += `<li>${field}: ${errors[field].join(', ')}</li>`;
                        error_message += `${field}: ${errors[field].join(', ')}`;
                    }
                    errorHtml += '</ul>';
                    $('#alertContainer').html(errorHtml).show();
                    // $('#alertContainer').fadeIn().delay(5000).fadeOut();
                    alert(error_message);
                    errorHtml = '';
                } else {
                    $('#alertContainer').html('Неизвестная ошибка.').show();
                }
            } else {
                alert(xhr.responseJSON.message);
            }
        }
    });
});