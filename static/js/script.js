document.addEventListener('DOMContentLoaded', () => {
    const submitBtn = document.getElementById('submit');
    const inputField = document.querySelector('.form-control');
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
            <div>
                <div class="flex-shrink-1 bg-primary text-white rounded py-2 px-3 mr-3 max-width-70 shadow-sm">
                    <div class="font-weight-bold mb-1 text-right">You</div>
                    ${escapeHtml(queryText)}
                </div>
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
            <div>
                <div class="flex-shrink-1 bg-dark text-light rounded py-2 px-3 ml-3 max-width-70 shadow-sm border border-secondary">
                    <div class="font-weight-bold mb-1">Quicks AI</div>
                    <div class="d-flex align-items-center">
                        <span class="spinner-border spinner-border-sm mr-2" role="status" aria-hidden="true"></span>
                        Thinking...
                    </div>
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
            data: { query: queryText }, // Send raw query text (fixes the JSON double-quoting bug)
            success: (response) => {
                // Update bot bubble with actual response
                const answerText = typeof response === 'string' ? response : (response.answer || JSON.stringify(response));
                botBubble.innerHTML = `
                    <div>
                        <div class="flex-shrink-1 bg-dark text-light rounded py-2 px-3 ml-3 max-width-70 shadow-sm border border-secondary">
                            <div class="font-weight-bold mb-1 text-info">Quicks AI</div>
                            <div>${escapeHtml(answerText).replace(/\n/g, '<br>')}</div>
                        </div>
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
                    <div>
                        <div class="flex-shrink-1 bg-danger text-white rounded py-2 px-3 ml-3 max-width-70 shadow-sm">
                            <div class="font-weight-bold mb-1">System Error</div>
                            <div>${escapeHtml(errorMessage)}</div>
                        </div>
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
