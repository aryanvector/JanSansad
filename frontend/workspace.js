// Topic suggestions only fill the search: users choose when to run a query.
document.querySelectorAll('[data-topic]').forEach(button => {
    button.addEventListener('click', () => {
        const input = document.getElementById('query-input');
        input.value = button.dataset.topic;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.focus();
    });
});

const searchButton = document.getElementById('submit-btn');
const searchFeedback = document.getElementById('search-feedback');
if (searchButton && searchFeedback) {
    new MutationObserver(() => {
        const busy = searchButton.disabled;
        document.getElementById('search-form').setAttribute('aria-busy', String(busy));
        searchFeedback.textContent = busy ? 'Searching parliamentary records. Please wait…' : '';
    }).observe(searchButton, {attributes:true, attributeFilter:['disabled']});
}
