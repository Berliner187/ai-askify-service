document.addEventListener("DOMContentLoaded", function() {
    const pageContainer = document.getElementById('page-container');
    
    pageContainer.classList.add('fade-in');
    
    const links = document.querySelectorAll('a');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const href = this.getAttribute('href');
            
            pageContainer.classList.remove('fade-in');
            
            setTimeout(() => {
                window.location.href = href;
            }, 500);
        });
    });
});
