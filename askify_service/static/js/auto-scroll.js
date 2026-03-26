const text = document.getElementById('user-text');
const slider = document.getElementById('question-slider');
const sliderValue = document.getElementById('slider-value');
const questionSliderText = document.getElementById('question-slider-text');
const charCount = document.getElementById('char-count');
const maxLength = 16384;

text.addEventListener('input', function() {
    // this.style.height = 'auto';
    // this.style.height = (this.scrollHeight) + 'px';

    if (this.value.length > maxLength) {
        this.value = this.value.substring(0, maxLength);
    }

    charCount.textContent = `${this.value.length} / ${maxLength}`;

    if (this.value.length >= maxLength) {
        charCount.classList.add('error');
    } else {
        charCount.classList.remove('error');
    }

    // if (this.value.trim() !== '') {
    //     slider.style.display = 'block';
    //     questionSliderText.style.display = 'block';
    //     slider.parentElement.classList.add('show');
    //     updateQuestionText(slider.value);
    // } else {
    //     slider.style.display = 'none';
    //     questionSliderText.style.display = 'none';
    //     slider.parentElement.classList.remove('show');
    // }
});

document.querySelectorAll('.topic').forEach(item => {
    item.addEventListener('click', () => {
        const textToInsert = item.getAttribute('data-text');
        const textarea = document.getElementById('user-text');
        textarea.value = textToInsert;

        charCount.textContent = `${text.value.length} / ${maxLength}`;

        if (text.value.length >= maxLength) {
            charCount.classList.add('error');
        } else {
            charCount.classList.remove('error');
        }

        if (text.value.trim() !== '') {
            slider.style.display = 'block';
            questionSliderText.style.display = 'block';
            slider.parentElement.classList.add('show');
            // updateQuestionText(slider.value);
        } else {
            slider.style.display = 'none';
            questionSliderText.style.display = 'none';
            slider.parentElement.classList.remove('show');
        }
    });
});

slider.addEventListener('input', function() {
    sliderValue.textContent = this.value;
});

text.style.height = (text.scrollHeight) + 'px';
