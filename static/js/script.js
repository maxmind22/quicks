document.addEventListener('DOMContentLoaded', () => {
    const submitBtn = document.getElementById('submit');
    const inputField = document.getElementById('search-input') || document.querySelector('.form-control');
    const resultsContainer = document.querySelector('.results');

    if (!submitBtn || !inputField || !resultsContainer) {
        return;
    }

    submitBtn.addEventListener('click', sendQuery);

    function sendQuery(e) {
        e.preventDefault();
        
        const queryText = inputField.value.trim();
        if (!queryText) return;

        // 1. Create and append User Message bubble
        const userBubble = document.createElement("div");
        userBubble.classList.add("chat-message-right", "pb-4");
        userBubble.innerHTML = `
            <div class="chat-bubble chat-bubble-user">
                <div class="chat-bubble-author text-end mb-1">You</div>
                <div class="chat-bubble-text">${escapeHtml(queryText)}</div>
            </div>
        `;
        resultsContainer.appendChild(userBubble);
        
        // Clear input and scroll to bottom
        inputField.value = "";
        scrollToBottom();

        // 2. Create and append Typing/Loading indicator bubble
        const botBubble = document.createElement("div");
        botBubble.classList.add("chat-message-left", "pb-4");
        
        const loadingHtml = `
            <div class="chat-bubble chat-bubble-ai">
                <div class="chat-bubble-author mb-1"><i class="fa-solid fa-robot me-1"></i>Quicks AI</div>
                <div class="d-flex align-items-center">
                    <span class="spinner-border spinner-border-sm me-2 text-primary" role="status" aria-hidden="true"></span>
                    <span>Searching documents & thinking...</span>
                </div>
            </div>
        `;
        botBubble.innerHTML = loadingHtml;
        resultsContainer.appendChild(botBubble);
        scrollToBottom();

        // 3. Send query to the server via AJAX
        $.ajax({
            url: "/search",
            type: "POST",
            data: { query: queryText },
            success: (response) => {
                // Update bot bubble with actual response
                const answerText = typeof response === 'string' ? response : (response.answer || JSON.stringify(response));
                botBubble.innerHTML = `
                    <div class="chat-bubble chat-bubble-ai">
                        <div class="chat-bubble-author mb-1"><i class="fa-solid fa-robot me-1"></i>Quicks AI</div>
                        <div class="chat-bubble-text">${escapeHtml(answerText).replace(/\n/g, '<br>')}</div>
                    </div>
                `;
                scrollToBottom();
            },
            error: (xhr, status, error) => {
                let errorMessage = "Sorry, something went wrong. Please try again.";
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    errorMessage = xhr.responseJSON.error;
                } else if (xhr.responseText) {
                    errorMessage = xhr.responseText;
                }
                botBubble.innerHTML = `
                    <div class="chat-bubble chat-bubble-danger">
                        <div class="chat-bubble-author mb-1"><i class="fa-solid fa-triangle-exclamation me-1"></i>System Error</div>
                        <div class="chat-bubble-text">${escapeHtml(errorMessage)}</div>
                    </div>
                `;
                scrollToBottom();
            }
        });
    }

    function scrollToBottom() {
        resultsContainer.scrollTop = resultsContainer.scrollHeight;
    }

    function escapeHtml(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    
    // Initial scroll to bottom
    scrollToBottom();
});
