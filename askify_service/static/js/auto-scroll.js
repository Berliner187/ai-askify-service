const text = document.getElementById('user-text');

text.addEventListener('input', function() {
    console.log("ok");
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

text.style.height = (text.scrollHeight) + 'px';
