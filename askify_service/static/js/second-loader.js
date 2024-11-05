window.addEventListener("load", function() {
    const loadingScreen = document.getElementById('loading-screen');
    const pageContainer = document.getElementById('page-container');

    loadingScreen.style.display = 'none';
    pageContainer.style.display = 'block';
    setTimeout(() => {
        pageContainer.classList.add('fade-in');
    }, 250);
});
