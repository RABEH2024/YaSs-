// --- START OF CORRECTED app.js ---
document.addEventListener('DOMContentLoaded', function() {
    // --- DOM Elements ---
    const messagesContainer = document.getElementById('messages');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const modelSelect = document.getElementById('model-select');
    const temperatureSlider = document.getElementById('temperature-slider');
    const temperatureValue = document.getElementById('temperature-value');
    const maxTokensInput = document.getElementById('max-tokens-input');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const ttsToggle = document.getElementById('tts-toggle');
    const offlineIndicator = document.getElementById('offline-indicator');
    const conversationsList = document.getElementById('conversations-list');
    const newConversationBtn = document.getElementById('new-conversation');
    const confirmModal = document.getElementById('confirm-modal');
    const confirmOkBtn = document.getElementById('confirm-ok');
    const confirmCancelBtn = document.getElementById('confirm-cancel');
    const confirmMessage = document.getElementById('confirm-message');
    const mobileMenuBtn = document.getElementById('mobile-menu');
    const mobileSettingsBtn = document.getElementById('mobile-settings');
    const sidebar = document.getElementById('settings-sidebar');
    const toggleSidebarBtn = document.getElementById('toggle-sidebar');

    // --- App State ---
    let currentConversationId = null; // *** FIX: Start with null ID. Let backend generate the first one. ***
    let currentModel = 'mistralai/mistral-7b-instruct'; // Default model
    let conversations = {}; // Object to store local conversation data { id: { title: '', messages: [] } }
    let isSendingMessage = false; // Flag to prevent multiple sends
    let confirmCallback = null; // For the confirm modal

    // --- Initialize App ---
    loadSettings();
    // Load conversations from backend API instead of localStorage for better persistence
    loadConversationsFromAPI();
    loadModels();
    checkOnlineStatus();

    // Listen for network status changes
    window.addEventListener('online', handleOnlineStatusChange);
    window.addEventListener('offline', handleOnlineStatusChange);

    // --- Event Listeners ---
    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    temperatureSlider.addEventListener('input', function() {
        temperatureValue.textContent = this.value;
        saveSettings();
    });
    modelSelect.addEventListener('change', function() {
        currentModel = this.value;
        saveSettings();
    });
    maxTokensInput.addEventListener('change', saveSettings);
    darkModeToggle.addEventListener('change', function() {
        document.body.classList.toggle('dark-mode', this.checked);
        saveSettings();
    });
    ttsToggle.addEventListener('change', saveSettings);
    newConversationBtn.addEventListener('click', startNewConversation);
    confirmOkBtn.addEventListener('click', function() {
        if (confirmCallback) confirmCallback();
        hideModal();
    });
    confirmCancelBtn.addEventListener('click', hideModal);
    mobileMenuBtn.addEventListener('click', toggleSidebar);
    mobileSettingsBtn.addEventListener('click', toggleSidebar);
    toggleSidebarBtn.addEventListener('click', toggleSidebar);

    // --- Functions ---

    // Send message to the AI
    async function sendMessage() {
        const messageText = messageInput.value.trim();
        if (!messageText || isSendingMessage) return;

        const userMessage = { role: 'user', content: messageText };

        // Add user message to UI immediately
        addMessageToUI('user', messageText);
        messageInput.value = ''; // Clear input

        // Store message locally temporarily if conversation exists
        if (currentConversationId && conversations[currentConversationId]) {
             conversations[currentConversationId].messages.push(userMessage);
        }

        // Show typing indicator
        showTypingIndicator();
        isSendingMessage = true;

        // Determine history to send (send full history if available)
        const historyToSend = (currentConversationId && conversations[currentConversationId])
                               ? conversations[currentConversationId].messages
                               : [userMessage]; // Send only user message if new convo

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: messageText, // Send current message text
                    model: currentModel,
                    // *** FIX: Send the current ID (null for new) ***
                    conversation_id: currentConversationId,
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value),
                    // Optionally send history if needed by backend strategy (though backend re-fetches)
                    // history: historyToSend
                })
            });

            removeTypingIndicator(); // Remove indicator once response (or error) received

            const data = await response.json();

            if (!response.ok) {
                // Display specific error from backend if available
                const errorMsg = data.error || `HTTP error ${response.status}`;
                console.error('Error from server:', errorMsg);
                addErrorMessageToUI(errorMsg); // Show error in UI
                // Remove the user message from local store if backend failed (optional)
                if (currentConversationId && conversations[currentConversationId]) {
                    conversations[currentConversationId].messages.pop();
                }
                return; // Stop processing on error
            }

            // --- Successful Response Handling ---
            const assistantMessage = { role: 'assistant', content: data.reply };

            // *** FIX: Handle receiving the conversation ID from the backend ***
            if (data.conversation_id && !currentConversationId) {
                // This was the first message of a *new* conversation
                currentConversationId = data.conversation_id;
                console.log("Received and set new conversation ID:", currentConversationId);

                // Create the conversation entry locally *now* using the backend ID
                conversations[currentConversationId] = {
                    id: currentConversationId,
                    title: extractTitle(messageText),
                    messages: [userMessage, assistantMessage] // Start with both messages
                };
                 // Highlight the new conversation in the sidebar
                updateConversationsList(true); // Pass true to indicate refresh needed

            } else if (currentConversationId && conversations[currentConversationId]) {
                // Add assistant message to existing local conversation
                conversations[currentConversationId].messages.push(assistantMessage);

                // Update title if it was the default "محادثة جديدة"
                 if (conversations[currentConversationId].title === 'محادثة جديدة' && conversations[currentConversationId].messages.length === 2) {
                    conversations[currentConversationId].title = extractTitle(messageText);
                    // Update title in the list without full refresh if possible
                    const listItem = conversationsList.querySelector(`.conversation-item[data-id="${currentConversationId}"] span`);
                    if(listItem) listItem.textContent = conversations[currentConversationId].title;
                }
            } else {
                 // Edge case: Received an ID but didn't expect one, or local state is inconsistent
                 console.error("State inconsistency: Received data for conversation ID", data.conversation_id, "but local state is unexpected.");
                 // Recover by treating as new conversation
                 currentConversationId = data.conversation_id;
                 conversations[currentConversationId] = { id: currentConversationId, title: extractTitle(messageText), messages: [userMessage, assistantMessage] };
                 updateConversationsList(true);
            }

            // Add AI response bubble to UI
            addMessageToUI('assistant', data.reply, true); // Pass true for AI message actions

            // Save conversations (optional, as we load from API now)
            // saveConversationsToLocalStorage();

            // Speak the response if TTS is enabled
            if (ttsToggle.checked && !data.offline) { // Don't speak offline messages unless desired
                speakText(data.reply);
            }

        } catch (error) {
            removeTypingIndicator();
            console.error('Fetch error:', error);
            addErrorMessageToUI('حدث خطأ في الشبكة أو في معالجة الرد. يرجى المحاولة مرة أخرى.');
             // Remove the user message from local store if fetch failed
            if (currentConversationId && conversations[currentConversationId]) {
                 // Find the user message added earlier and remove it
                 const lastUserMsgIndex = conversations[currentConversationId].messages.findLastIndex(m => m.role === 'user');
                 if (lastUserMsgIndex > -1 && conversations[currentConversationId].messages[lastUserMsgIndex].content === messageText) {
                     conversations[currentConversationId].messages.splice(lastUserMsgIndex, 1);
                 }
            }
        } finally {
            isSendingMessage = false; // Allow sending again
        }
    }

     // Call the Regenerate API
    async function regenerateResponse(messageElement) {
        if (isSendingMessage || !currentConversationId || !conversations[currentConversationId]) return;

        const conversation = conversations[currentConversationId];
        const currentMessages = conversation.messages;

        // Find the index of the AI message to regenerate by searching backwards
        let messageToRegenerateIndex = -1;
        for(let i = currentMessages.length - 1; i >= 0; i--) {
            if (currentMessages[i].role === 'assistant') {
                messageToRegenerateIndex = i;
                break;
            }
        }

        if (messageToRegenerateIndex < 1) { // Need at least one user message before it
            console.error("Cannot regenerate the first message or no preceding user message found.");
            addErrorMessageToUI("لا يمكن إعادة توليد هذه الرسالة.");
            return;
        }

        // Get history UP TO the message BEFORE the one being regenerated
        const historyForApi = currentMessages.slice(0, messageToRegenerateIndex);

        // Show indicator near the message being regenerated
        showTypingIndicator(messageElement); // Pass element to place indicator after
        messageElement.style.opacity = '0.5'; // Dim the message being replaced
        isSendingMessage = true;

        try {
            const response = await fetch('/api/regenerate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    // Send the history *before* the message to regenerate
                    messages: historyForApi,
                    model: currentModel,
                    conversation_id: currentConversationId, // Must be the correct backend ID
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value)
                })
            });

            removeTypingIndicator(); // Remove indicator always

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP error ${response.status}`);
            }

            const regeneratedContent = data.reply;

            // Update the message content in the UI
            const contentElement = messageElement.querySelector('p');
            if (contentElement) {
                contentElement.textContent = regeneratedContent;
            }
            messageElement.style.opacity = '1'; // Restore opacity

            // Update the message content in the local state
            conversation.messages[messageToRegenerateIndex].content = regeneratedContent;
            // Optionally update timestamp if backend provides it

            // Save conversations (optional)
            // saveConversationsToLocalStorage();

            // Speak if enabled
            if (ttsToggle.checked) {
                speakText(regeneratedContent);
            }

        } catch (error) {
            removeTypingIndicator();
            messageElement.style.opacity = '1'; // Restore opacity on error too
            console.error('Regenerate error:', error);
            addErrorMessageToUI(`فشل إعادة التوليد: ${error.message}`);
        } finally {
            isSendingMessage = false;
        }
    }


    // Add a message bubble to the UI
    function addMessageToUI(role, content, isAI = false, convId = null) {
        const bubble = document.createElement('div');
        bubble.className = `message-bubble ${role === 'user' ? 'user' : 'ai'}-bubble`;
        // Add data-id if needed for specific targeting
        // bubble.dataset.messageId = some_unique_id_if_available;

        const text = document.createElement('p');
        // Render Markdown (basic example, consider a library like 'marked' for full features)
        text.innerHTML = basicMarkdownToHtml(content);
        bubble.appendChild(text);

        // Add action buttons
        const actions = document.createElement('div');
        actions.className = 'message-actions';

        // Copy button (always add)
        const copyBtn = createActionButton('copy-btn', 'نسخ', 'fas fa-copy', () => copyToClipboard(content));
        actions.appendChild(copyBtn);

        // Buttons specific to AI messages
        if (isAI) {
            const regenerateBtn = createActionButton('regenerate-btn', 'إعادة التوليد', 'fas fa-redo-alt', () => regenerateResponse(bubble));
            actions.appendChild(regenerateBtn);

            const speakBtn = createActionButton('speak-btn', 'استماع', 'fas fa-volume-up', () => speakText(content));
            actions.appendChild(speakBtn);
        }

        bubble.appendChild(actions);
        messagesContainer.appendChild(bubble);

        // Scroll to bottom smoothly
        messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
    }

     // Helper to create action buttons
    function createActionButton(className, title, iconClass, onClick) {
        const button = document.createElement('button');
        button.className = className;
        button.title = title;
        button.innerHTML = `<i class="${iconClass}"></i>`;
        button.addEventListener('click', onClick);
        return button;
    }

     // Add an error message bubble to the UI
    function addErrorMessageToUI(message) {
        const errorBubble = document.createElement('div');
        errorBubble.className = 'message-bubble error-bubble ai-bubble'; // Style like AI bubble but maybe red?
        errorBubble.style.backgroundColor = 'var(--danger-color, #f8d7da)'; // Use CSS var or fallback
        errorBubble.style.color = 'var(--danger-text-color, #721c24)';
        errorBubble.style.borderColor = 'var(--danger-border-color, #f5c6cb)';
        errorBubble.style.border = '1px solid';

        const text = document.createElement('p');
        text.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${message}`;
        errorBubble.appendChild(text);

        messagesContainer.appendChild(errorBubble);
        messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
    }


    // Load messages for a specific conversation from the backend
    async function loadConversationMessages(conversationId) {
        messagesContainer.innerHTML = ''; // Clear existing messages

        if (!conversationId) {
             addWelcomeMessage();
             return;
        }

        // Check local cache first (optional optimization)
        if (conversations[conversationId] && conversations[conversationId].messages.length > 0) {
            console.log(`Loading conversation ${conversationId} from local cache`);
            conversations[conversationId].messages.forEach(msg => {
                 addMessageToUI(msg.role, msg.content, msg.role === 'assistant');
            });
            // Optionally, still fetch from API in background to ensure freshness
            // fetchConversationFromAPI(conversationId, false); // Don't clear UI again
            return;
        }

        // Fetch from API if not in cache or cache is empty
        console.log(`Fetching conversation ${conversationId} from API`);
        await fetchConversationFromAPI(conversationId, true); // Clear UI is true by default here
    }

    async function fetchConversationFromAPI(conversationId, clearUI = true) {
         if (clearUI) {
            messagesContainer.innerHTML = ''; // Clear messages container
         }
         showLoadingIndicator(); // Show loading state

         try {
            const response = await fetch(`/api/conversations/${conversationId}`);
            removeLoadingIndicator(); // Remove loading state

            if (!response.ok) {
                // Handle case where conversation is not found on backend (e.g., deleted elsewhere)
                if (response.status === 404) {
                     console.warn(`Conversation ${conversationId} not found on backend.`);
                     delete conversations[conversationId]; // Remove from local state
                     // saveConversationsToLocalStorage(); // Update local storage
                     startNewConversation(); // Start a fresh one
                     updateConversationsList(true);
                     addErrorMessageToUI("لم يتم العثور على المحادثة المطلوبة. تم بدء محادثة جديدة.");
                } else {
                    const data = await response.json();
                    throw new Error(data.error || `HTTP error ${response.status}`);
                }
                return;
            }

            const data = await response.json();

            // Update local cache with fetched data
            conversations[conversationId] = {
                id: conversationId,
                title: data.title || 'محادثة جديدة',
                messages: data.messages || []
            };
            // saveConversationsToLocalStorage(); // Update local storage

            if (clearUI) { // Only add messages if we cleared the UI
                 if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(msg => {
                        addMessageToUI(msg.role, msg.content, msg.role === 'assistant');
                    });
                } else {
                    // If conversation exists but has no messages, show welcome
                     addWelcomeMessage();
                }
            }
            // Ensure the correct item is marked active in the sidebar
            setActiveConversationItem(conversationId);

        } catch (error) {
             removeLoadingIndicator();
             console.error(`Error fetching conversation ${conversationId}:`, error);
             addErrorMessageToUI(`حدث خطأ أثناء تحميل المحادثة: ${error.message}`);
             // Potentially fall back to local version if available, or start new convo
             if (!conversations[conversationId] && clearUI) {
                startNewConversation(); // Fallback to new convo if load fails completely
             }
        }
    }

    // Start a new conversation flow
    function startNewConversation() {
        currentConversationId = null; // *** FIX: Set ID to null ***
        messagesContainer.innerHTML = ''; // Clear messages UI
        addWelcomeMessage(); // Show initial welcome message
        setActiveConversationItem(null); // Deactivate items in sidebar list
        messageInput.value = ''; // Clear input field
        messageInput.focus(); // Focus input
        console.log("Starting a new conversation session.");

        // Close sidebar on mobile
        if (window.innerWidth <= 768 && sidebar.classList.contains('active')) {
            sidebar.classList.remove('active');
        }
    }

    // Switch to a specific conversation
    function switchConversation(conversationId) {
        if (conversationId === currentConversationId) {
             // If already active, maybe just close sidebar on mobile
             if (window.innerWidth <= 768 && sidebar.classList.contains('active')) {
                sidebar.classList.remove('active');
             }
             return;
        }

        console.log(`Switching to conversation: ${conversationId}`);
        currentConversationId = conversationId;
        loadConversationMessages(conversationId); // Load messages from cache/API
        setActiveConversationItem(conversationId); // Update active class in the list

        // Close sidebar on mobile after switching
        if (window.innerWidth <= 768 && sidebar.classList.contains('active')) {
            sidebar.classList.remove('active');
        }
    }

    // Delete a conversation from backend and frontend
    function deleteConversation(conversationId) {
        const conversationTitle = conversations[conversationId]?.title || `المحادثة (${conversationId.substring(0, 6)}...)`;
        confirmMessage.textContent = `هل أنت متأكد من أنك تريد حذف "${conversationTitle}"؟`;
        showModal(async () => { // Make confirmation callback async
            console.log(`Attempting to delete conversation: ${conversationId}`);
            try {
                const response = await fetch(`/api/conversations/${conversationId}`, {
                    method: 'DELETE',
                });

                const data = await response.json(); // Try to parse JSON even for errors

                if (!response.ok) {
                     throw new Error(data.error || `HTTP error ${response.status}`);
                }

                console.log(`Successfully deleted conversation ${conversationId} from backend.`);

                // Remove from frontend state
                delete conversations[conversationId];
                // saveConversationsToLocalStorage(); // Update local storage

                // If the deleted conversation was the current one, start a new one
                if (conversationId === currentConversationId) {
                    startNewConversation();
                }
                 updateConversationsList(true); // Refresh the list


            } catch (error) {
                 console.error(`Error deleting conversation ${conversationId}:`, error);
                 addErrorMessageToUI(`فشل حذف المحادثة: ${error.message}`);
                 // Optionally, only remove from frontend if backend fails? Or leave it?
                 // For now, we leave it locally if backend delete fails.
            }
        });
    }

    // Update the conversations list display in the sidebar
    function updateConversationsList(forceRefresh = false) {
        // If not forcing a refresh, maybe just update titles/active state?
        // For simplicity now, we always redraw the list.

        conversationsList.innerHTML = ''; // Clear the list

        // Get conversation entries sorted by updated_at (if available) or created_at
        // Sorting requires timestamps in the local 'conversations' object, which we aren't storing reliably yet.
        // Simple sort by key for now (which is not ideal). Fetching from API provides sorting.
        const sortedIds = Object.keys(conversations); // .sort(...) using timestamps if available

        if (sortedIds.length === 0) {
            conversationsList.appendChild(createEmptyStateElement());
            return;
        }

        sortedIds.forEach(id => {
            const conversation = conversations[id];
            if (!conversation) return; // Skip if data is missing

            const item = document.createElement('div');
            item.className = 'conversation-item';
            item.dataset.id = id;
            item.classList.toggle('active', id === currentConversationId); // Set active based on current ID

            const titleSpan = document.createElement('span');
            titleSpan.textContent = conversation.title || 'محادثة جديدة'; // Use title from local cache
            item.appendChild(titleSpan);

            const actionsDiv = document.createElement('div');
            actionsDiv.className = 'conversation-actions';

            const deleteBtn = createActionButton('delete-btn icon-button', 'حذف المحادثة', 'fas fa-trash', (e) => {
                e.stopPropagation(); // Prevent conversation switch on button click
                deleteConversation(id);
            });
            actionsDiv.appendChild(deleteBtn);

            item.appendChild(actionsDiv);

            item.addEventListener('click', () => switchConversation(id));
            conversationsList.appendChild(item);
        });
    }

     // Load conversations list from the backend API
    async function loadConversationsFromAPI() {
        console.log("Loading conversation list from API...");
        conversationsList.innerHTML = ''; // Clear existing list
        conversationsList.appendChild(createLoadingStateElement("جاري تحميل المحادثات..."));

        try {
            const response = await fetch('/api/conversations');
            conversationsList.innerHTML = ''; // Clear loading indicator

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || `HTTP error ${response.status}`);
            }

            const data = await response.json();

            // Reset local conversations and populate with data from API
            conversations = {};
            if (data.conversations && data.conversations.length > 0) {
                 data.conversations.forEach(conv => {
                     conversations[conv.id] = { // Store basic info locally
                         id: conv.id,
                         title: conv.title,
                         messages: [], // Messages will be loaded on demand
                         updated_at: conv.updated_at // Store timestamp if needed for sorting
                     };
                 });

                 // Set the current conversation ID to the most recent one (first in the sorted list)
                 // Only set if currentConversationId is currently null (on initial load)
                 if (currentConversationId === null) {
                     currentConversationId = data.conversations[0].id;
                     // Load messages for the initially selected conversation
                     loadConversationMessages(currentConversationId);
                 }

            } else {
                 // No conversations on backend, start a new one locally
                 startNewConversation();
            }

            updateConversationsList(); // Update the sidebar display

        } catch (error) {
             console.error("Error loading conversation list:", error);
             conversationsList.innerHTML = ''; // Clear loading indicator
             conversationsList.appendChild(createEmptyStateElement(`خطأ في تحميل المحادثات: ${error.message}`));
             // Fallback: start a new conversation locally if API load fails
             if (Object.keys(conversations).length === 0) {
                 startNewConversation();
             }
        }
    }


    // Helper to create empty/loading states for the list
    function createEmptyStateElement(text = 'لا توجد محادثات سابقة') {
        const emptyState = document.createElement('div');
        emptyState.className = 'empty-state';
        emptyState.textContent = text;
        return emptyState;
    }
    function createLoadingStateElement(text = 'جاري التحميل...') {
        const loadingState = document.createElement('div');
        loadingState.className = 'empty-state'; // Reuse styling
        loadingState.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${text}`;
        return loadingState;
    }


    // Load available models from API
    async function loadModels() {
        try {
            const response = await fetch('/api/models');
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            const data = await response.json();

            modelSelect.innerHTML = ''; // Clear existing options
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.name;
                option.selected = (model.id === currentModel); // Select the current model
                modelSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Error loading models:', error);
            // Keep default option if API fails
            if (modelSelect.options.length === 0) {
                 const defaultOption = document.createElement('option');
                 defaultOption.value = currentModel;
                 defaultOption.textContent = currentModel.split('/')[1] || currentModel; // Basic name
                 modelSelect.appendChild(defaultOption);
            }
        }
    }

    // Save app settings to localStorage
    function saveSettings() {
        const settings = {
            darkMode: darkModeToggle.checked,
            ttsEnabled: ttsToggle.checked,
            model: modelSelect.value,
            temperature: temperatureSlider.value,
            maxTokens: maxTokensInput.value
        };
        localStorage.setItem('yasminSettings', JSON.stringify(settings));
        currentModel = modelSelect.value; // Update state variable
    }

    // Load app settings from localStorage
    function loadSettings() {
        const settings = JSON.parse(localStorage.getItem('yasminSettings'));
        if (settings) {
            darkModeToggle.checked = settings.darkMode;
            document.body.classList.toggle('dark-mode', settings.darkMode);
            ttsToggle.checked = settings.ttsEnabled || false;
            temperatureSlider.value = settings.temperature || 0.7;
            temperatureValue.textContent = temperatureSlider.value;
            maxTokensInput.value = settings.maxTokens || 1024; // Match backend default
            currentModel = settings.model || 'mistralai/mistral-7b-instruct';
            // modelSelect value is set after loadModels() finishes
        } else {
            // Apply default dark mode based on system preference if no setting saved
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                darkModeToggle.checked = true;
                document.body.classList.add('dark-mode');
            }
        }
    }

    // --- Utility Functions ---

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(() => {
            showTemporaryNotification('تم النسخ بنجاح!');
        }).catch(err => {
            console.error('Failed to copy text: ', err);
            showTemporaryNotification('فشل النسخ!', true);
        });
    }

    function showTemporaryNotification(message, isError = false) {
        const notification = document.createElement('div');
        // Basic styling, consider using a dedicated notification library
        notification.style.position = 'fixed';
        notification.style.bottom = '20px';
        notification.style.left = '50%';
        notification.style.transform = 'translateX(-50%)';
        notification.style.padding = '10px 20px';
        notification.style.borderRadius = '5px';
        notification.style.zIndex = '2000';
        notification.style.backgroundColor = isError ? '#dc3545' : '#28a745';
        notification.style.color = 'white';
        notification.style.opacity = '1';
        notification.style.transition = 'opacity 0.5s ease-out';
        notification.textContent = message;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 500); // Remove from DOM after fade out
        }, 2500); // Notification visible for 2.5 seconds
    }


    function speakText(text) {
        if ('speechSynthesis' in window && ttsToggle.checked) {
            window.speechSynthesis.cancel(); // Cancel previous speech
            const utterance = new SpeechSynthesisUtterance(text);
            // Attempt to find a suitable Arabic voice
            const voices = speechSynthesis.getVoices();
            const arabicVoice = voices.find(voice => voice.lang.startsWith('ar-'));
            if (arabicVoice) {
                utterance.voice = arabicVoice;
                 utterance.lang = arabicVoice.lang; // Use voice's specific lang
            } else {
                 utterance.lang = 'ar-SA'; // Fallback language
                 console.warn("No specific Arabic voice found, using default.");
            }
            utterance.rate = 1.0; // Adjust speech rate if needed
            utterance.pitch = 1.0; // Adjust pitch if needed
            window.speechSynthesis.speak(utterance);
        } else if (!('speechSynthesis' in window)) {
             console.warn("Speech synthesis not supported by this browser.");
             ttsToggle.checked = false; // Disable toggle if not supported
             saveSettings();
        }
    }


    function checkOnlineStatus() {
        offlineIndicator.style.display = navigator.onLine ? 'none' : 'block';
    }
    function handleOnlineStatusChange() { checkOnlineStatus(); }
    function toggleSidebar() { sidebar.classList.toggle('active'); }

    function showModal(callback) {
        confirmModal.style.display = 'flex';
        confirmCallback = callback;
    }
    function hideModal() {
        confirmModal.style.display = 'none';
        confirmCallback = null;
    }

    // Simple Markdown to HTML (bold and italics only)
    function basicMarkdownToHtml(text) {
         if (typeof text !== 'string') return '';
         return text
             .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold
             .replace(/\*(.*?)\*/g, '<em>$1</em>');       // Italics
     }

     // Add Welcome Message
     function addWelcomeMessage() {
         addMessageToUI('ai', 'السلام عليكم! أنا ياسمين، مساعدتك الرقمية بالعربية. كيف يمكنني مساعدتك اليوم؟', true);
     }

     // Show/Hide Typing Indicator
     let typingIndicatorElement = null;
     function showTypingIndicator(referenceElement = null) {
         if (typingIndicatorElement) removeTypingIndicator(); // Remove existing if any
         typingIndicatorElement = document.createElement('div');
         typingIndicatorElement.className = 'message-bubble ai-bubble typing-indicator'; // Style like AI bubble
         typingIndicatorElement.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> ياسمين تكتب...'; // Use FontAwesome icon

         if (referenceElement && referenceElement.parentNode === messagesContainer) {
             // Insert after the reference element (e.g., the message being regenerated)
             messagesContainer.insertBefore(typingIndicatorElement, referenceElement.nextSibling);
         } else {
             // Append to the end
             messagesContainer.appendChild(typingIndicatorElement);
         }
         messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
     }

     function removeTypingIndicator() {
         if (typingIndicatorElement && typingIndicatorElement.parentNode) {
             typingIndicatorElement.parentNode.removeChild(typingIndicatorElement);
         }
         typingIndicatorElement = null;
     }

     // Show/Hide Loading Indicator for conversation load
     let loadingIndicatorElement = null;
     function showLoadingIndicator() {
          if (loadingIndicatorElement) removeLoadingIndicator();
          loadingIndicatorElement = document.createElement('div');
          loadingIndicatorElement.className = 'empty-state'; // Reuse styling
          loadingIndicatorElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري تحميل الرسائل...';
          messagesContainer.appendChild(loadingIndicatorElement);
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
     }
      function removeLoadingIndicator() {
         if (loadingIndicatorElement && loadingIndicatorElement.parentNode) {
             loadingIndicatorElement.parentNode.removeChild(loadingIndicatorElement);
         }
         loadingIndicatorElement = null;
     }

     // Set active item in sidebar
     function setActiveConversationItem(activeId) {
         const items = conversationsList.querySelectorAll('.conversation-item');
         items.forEach(item => {
             item.classList.toggle('active', item.dataset.id === activeId);
         });
     }

    // Initial welcome message display (moved from loadConversationMessages)
    if (!currentConversationId) {
        addWelcomeMessage();
    }

});
// --- END OF CORRECTED app.js ---
