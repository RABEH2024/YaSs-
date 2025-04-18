document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Element Selection ---
    const sidebar = document.getElementById('settings-sidebar');
    const chatContainer = document.getElementById('chat-container');
    const messagesContainer = document.getElementById('messages');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const modelSelect = document.getElementById('model-select');
    const temperatureSlider = document.getElementById('temperature-slider');
    const temperatureValue = document.getElementById('temperature-value');
    const maxTokensInput = document.getElementById('max-tokens-input');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const ttsToggle = document.getElementById('tts-toggle');
    const newConversationButton = document.getElementById('new-conversation');
    const conversationsList = document.getElementById('conversations-list');
    const typingIndicator = document.getElementById('typing-indicator');
    const offlineIndicator = document.getElementById('offline-indicator');
    const currentConversationTitle = document.getElementById('current-conversation-title');

    // Mobile specific
    const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
    const mobileCloseSidebar = document.getElementById('mobile-close-sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    // Modals
    const confirmModal = document.getElementById('confirm-modal');
    const confirmMessage = document.getElementById('confirm-message');
    const confirmOkButton = document.getElementById('confirm-ok');
    const confirmCancelButton = document.getElementById('confirm-cancel');
    const errorModal = document.getElementById('error-modal');
    const errorMessage = document.getElementById('error-message');
    const errorOkButton = document.getElementById('error-ok');

    // --- State Variables ---
    let currentConversationId = null;
    let messageHistory = []; // Holds messages for the current conversation {role: 'user'/'assistant', content: '...'}
    let conversations = {}; // Store loaded conversation list {id: {id, title, updated_at}}
    let isDeleting = false; // Prevent actions during delete confirmation
    let confirmCallback = null; // Callback for confirmation modal

    // Speech Synthesis
    let synth = window.speechSynthesis;
    let utterance = new SpeechSynthesisUtterance();
    let isTTSEnabled = localStorage.getItem('ttsEnabled') === 'true';
    ttsToggle.checked = isTTSEnabled;


    // --- Initialization ---

    // 1. Dark Mode
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
    const currentTheme = localStorage.getItem('theme');
    if (currentTheme === 'dark' || (!currentTheme && prefersDark.matches)) {
        document.body.classList.add('dark-mode');
        darkModeToggle.checked = true;
    }
    darkModeToggle.addEventListener('change', toggleDarkMode);
    prefersDark.addEventListener('change', (e) => { // Listen for OS theme changes
        if (!localStorage.getItem('theme')) { // Only if user hasn't manually set
             if(e.matches) {
                  document.body.classList.add('dark-mode');
                  darkModeToggle.checked = true;
             } else {
                  document.body.classList.remove('dark-mode');
                  darkModeToggle.checked = false;
             }
        }
    });

    // 2. Settings Persistence
    temperatureSlider.value = localStorage.getItem('temperature') || 0.7;
    temperatureValue.textContent = temperatureSlider.value;
    maxTokensInput.value = localStorage.getItem('maxTokens') || 512;

    temperatureSlider.addEventListener('input', () => {
        temperatureValue.textContent = temperatureSlider.value;
    });
    temperatureSlider.addEventListener('change', () => {
        localStorage.setItem('temperature', temperatureSlider.value);
    });
    maxTokensInput.addEventListener('change', () => {
        localStorage.setItem('maxTokens', maxTokensInput.value);
    });

     // 3. TTS Toggle Persistence
    ttsToggle.addEventListener('change', () => {
        isTTSEnabled = ttsToggle.checked;
        localStorage.setItem('ttsEnabled', isTTSEnabled);
        if (!isTTSEnabled && synth.speaking) { // Stop speaking if disabled
            synth.cancel();
        }
    });

    // 4. Load Models
    loadModels();

    // 5. Load Conversations
    loadConversations();

    // 6. Event Listeners
    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', handleInputKeydown);
    messageInput.addEventListener('input', autoResizeInput);
    newConversationButton.addEventListener('click', startNewConversation);

    // Modal listeners
    confirmCancelButton.addEventListener('click', hideConfirmModal);
    confirmOkButton.addEventListener('click', handleConfirm);
    errorOkButton.addEventListener('click', hideErrorModal);

     // Mobile Sidebar Listeners
    mobileMenuToggle.addEventListener('click', toggleMobileSidebar);
    mobileCloseSidebar.addEventListener('click', toggleMobileSidebar);
    sidebarOverlay.addEventListener('click', toggleMobileSidebar); // Close on overlay click

    // Dynamic listeners for conversation list and message actions (added via delegation)
    conversationsList.addEventListener('click', handleConversationListClick);
    messagesContainer.addEventListener('click', handleMessageActionsClick);

    // Initial input resize
    autoResizeInput();

    // --- Core Functions ---

    function toggleDarkMode() {
        if (darkModeToggle.checked) {
            document.body.classList.add('dark-mode');
            localStorage.setItem('theme', 'dark');
        } else {
            document.body.classList.remove('dark-mode');
            localStorage.setItem('theme', 'light');
        }
    }

    function toggleMobileSidebar() {
        sidebar.classList.toggle('active');
        sidebarOverlay.classList.toggle('active');
    }

    async function loadModels() {
        try {
            const response = await fetch('/api/models');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            modelSelect.innerHTML = ''; // Clear loading state
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.name;
                modelSelect.appendChild(option);
            });
            // Set selected model from local storage or default
             const savedModel = localStorage.getItem('selectedModel');
             if (savedModel && modelSelect.querySelector(`option[value="${savedModel}"]`)) {
                 modelSelect.value = savedModel;
             } else if (data.models.length > 0) {
                  modelSelect.value = data.models[0].id; // Default to first model
                  localStorage.setItem('selectedModel', modelSelect.value);
             }
        } catch (error) {
            console.error("Error loading models:", error);
            modelSelect.innerHTML = '<option value="">Failed to load</option>';
            showError("فشل تحميل قائمة النماذج.");
        }
         modelSelect.addEventListener('change', () => {
             localStorage.setItem('selectedModel', modelSelect.value);
         });
    }

    async function loadConversations() {
        try {
            conversationsList.innerHTML = '<div class="empty-state">جاري تحميل المحادثات...</div>';
            const response = await fetch('/api/conversations');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            renderConversationList(data.conversations);
            // Optionally load the last active conversation
            const lastConvId = localStorage.getItem('lastConversationId');
             if (lastConvId && conversations[lastConvId]) {
                 loadConversation(lastConvId);
             } else if (data.conversations.length > 0) {
                 // Load the most recent one if none was saved
                 // loadConversation(data.conversations[0].id);
                 // Or just start fresh
                 startNewConversation();
             } else {
                  startNewConversation(); // Start new if no history
             }

        } catch (error) {
            console.error("Error loading conversations:", error);
            conversationsList.innerHTML = '<div class="empty-state">فشل تحميل المحادثات.</div>';
            showError("فشل تحميل قائمة المحادثات.");
            startNewConversation(); // Start fresh on error
        }
    }

    function renderConversationList(convs) {
         conversationsList.innerHTML = ''; // Clear existing list
         conversations = {}; // Reset local cache
         if (convs && convs.length > 0) {
             convs.forEach(conv => {
                 conversations[conv.id] = conv; // Update cache
                 const convElement = document.createElement('div');
                 convElement.classList.add('conversation-item');
                 convElement.dataset.id = conv.id;
                 convElement.innerHTML = `
                     <span class="conv-title">${escapeHtml(conv.title)}</span>
                     <div class="conversation-actions">
                         <button class="icon-button delete-conv-btn" title="حذف المحادثة">
                             <i class="fas fa-trash-alt"></i>
                         </button>
                     </div>
                 `;
                 // Mark active conversation
                 if (conv.id === currentConversationId) {
                     convElement.classList.add('active');
                 }
                 conversationsList.appendChild(convElement);
             });
         } else {
             conversationsList.innerHTML = '<div class="empty-state">لا توجد محادثات سابقة.</div>';
         }
     }

     function handleConversationListClick(event) {
          const target = event.target;
          const conversationItem = target.closest('.conversation-item');

          if (target.closest('.delete-conv-btn') && conversationItem) {
              // Delete button clicked
              const convId = conversationItem.dataset.id;
              if (!isDeleting) {
                  showConfirmModal(`هل أنت متأكد من حذف المحادثة "${conversations[convId]?.title || 'المحددة'}"؟`, () => {
                      deleteConversation(convId);
                  });
              }
          } else if (conversationItem) {
              // Conversation item clicked (but not delete button)
              const convId = conversationItem.dataset.id;
              if (convId !== currentConversationId) {
                   loadConversation(convId);
                   // Close sidebar on mobile after selection
                   if (window.innerWidth <= 768) {
                        toggleMobileSidebar();
                   }
              }
          }
      }

    function startNewConversation() {
        currentConversationId = null;
        messageHistory = [];
        messagesContainer.innerHTML = ''; // Clear messages display
        addWelcomeMessage(); // Add initial welcome message
        currentConversationTitle.textContent = "محادثة جديدة";
        localStorage.removeItem('lastConversationId');
        messageInput.value = '';
        autoResizeInput();
        messageInput.focus();
         // Deactivate all items in list
         document.querySelectorAll('.conversation-item.active').forEach(el => el.classList.remove('active'));
         console.log("Started new conversation");
    }

     async function loadConversation(convId) {
        console.log(`Loading conversation ${convId}`);
         if (!convId) return startNewConversation();
         // Show loading state?
         try {
             const response = await fetch(`/api/conversations/${convId}`);
             if (!response.ok) {
                 if (response.status === 404) {
                     showError("المحادثة المطلوبة غير موجودة.");
                     localStorage.removeItem('lastConversationId');
                     return loadConversations(); // Reload list and start fresh
                 }
                 throw new Error(`HTTP error! status: ${response.status}`);
             }
             const data = await response.json();

             currentConversationId = convId;
             messageHistory = data.messages.map(msg => ({ role: msg.role, content: msg.content })); // Rebuild history
             messagesContainer.innerHTML = ''; // Clear existing messages
             messageHistory.forEach(addMessageToUI); // Add messages to UI
             currentConversationTitle.textContent = data.title || "محادثة";
             localStorage.setItem('lastConversationId', convId);

             // Update active state in the list
             document.querySelectorAll('.conversation-item.active').forEach(el => el.classList.remove('active'));
             const activeItem = conversationsList.querySelector(`.conversation-item[data-id="${convId}"]`);
             if (activeItem) {
                 activeItem.classList.add('active');
             }

             scrollToBottom();
             messageInput.focus();

         } catch (error) {
             console.error(`Error loading conversation ${convId}:`, error);
             showError(`فشل تحميل المحادثة: ${error.message}`);
             // Fallback to new conversation
             startNewConversation();
         }
     }

    async function deleteConversation(convId) {
        if (!convId) return;
        console.log(`Deleting conversation ${convId}`);
        try {
            const response = await fetch(`/api/conversations/${convId}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();

            if (data.success) {
                 // Remove from local cache and UI list
                 delete conversations[convId];
                 const itemToRemove = conversationsList.querySelector(`.conversation-item[data-id="${convId}"]`);
                 if (itemToRemove) itemToRemove.remove();

                 // If the deleted conversation was the current one, start new
                 if (convId === currentConversationId) {
                     startNewConversation();
                 }
                 // Check if list is now empty
                 if (conversationsList.children.length === 0) {
                     conversationsList.innerHTML = '<div class="empty-state">لا توجد محادثات سابقة.</div>';
                 }
            } else {
                throw new Error(data.error || "فشل حذف المحادثة.");
            }
        } catch (error) {
            console.error(`Error deleting conversation ${convId}:`, error);
            showError(`فشل حذف المحادثة: ${error.message}`);
        }
    }


    function handleInputKeydown(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault(); // Prevent default newline insertion
            sendMessage();
        }
    }

     function autoResizeInput() {
        messageInput.style.height = 'auto'; // Reset height
        let scrollHeight = messageInput.scrollHeight;
        const maxHeight = 150; // Match CSS max-height

        if (scrollHeight > maxHeight) {
             messageInput.style.height = `${maxHeight}px`;
             messageInput.style.overflowY = 'auto'; // Enable scroll
        } else {
             messageInput.style.height = `${scrollHeight}px`;
             messageInput.style.overflowY = 'hidden'; // Disable scroll
        }
     }


    async function sendMessage() {
        const userMessage = messageInput.value.trim();
        if (!userMessage) return;

        // Disable input and show typing indicator
        messageInput.value = '';
        autoResizeInput(); // Reset height after clearing
        messageInput.disabled = true;
        sendButton.disabled = true;
        showTypingIndicator(true);

        // Add user message to UI and history
        addMessageToUI({ role: 'user', content: userMessage });
        messageHistory.push({ role: 'user', content: userMessage });
        scrollToBottom();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: userMessage,
                    model: modelSelect.value,
                    history: messageHistory.slice(0, -1), // Send history *before* the current user message
                    conversation_id: currentConversationId,
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value)
                })
            });

            const data = await response.json();

            if (!response.ok) {
                 // Handle specific error codes if needed (e.g., 400 Bad Request, 503 Service Unavailable)
                 throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            // Process successful response
             const aiReply = data.reply;
             currentConversationId = data.conversation_id; // Update conversation ID if new
             localStorage.setItem('lastConversationId', currentConversationId); // Save current ID

             // Add AI reply to UI and history
             addMessageToUI({ role: 'assistant', content: aiReply }, data.backup_used, data.offline);
             messageHistory.push({ role: 'assistant', content: aiReply });

             // Optionally show offline indicator
             showOfflineIndicator(data.offline);
             if(data.offline && data.error) {
                  console.warn("Offline mode with error:", data.error);
                  // Optionally display the error subtly or just rely on the offline indicator
             }
             if(!data.offline && data.error) {
                 // This case might happen if APIs failed but DB save also failed etc.
                 showError(data.error); // Show backend error if provided even with a reply
             }


             // If it was the first message of a new conversation, reload the list
             if (messageHistory.length <= 2) {
                 loadConversations(); // Reload to show the new conversation title
             } else {
                  // Update the timestamp/position of the current conversation in the list (optional)
                  updateConversationTimestamp(currentConversationId);
             }


        } catch (error) {
            console.error("Error sending message:", error);
            // Add an error message to the chat UI
            addMessageToUI({ role: 'system', content: `حدث خطأ: ${error.message}` });
            showError(`فشل إرسال الرسالة: ${error.message}`); // Also show in modal
        } finally {
            // Re-enable input and hide indicator regardless of success/failure
            messageInput.disabled = false;
            sendButton.disabled = false;
            showTypingIndicator(false);
            messageInput.focus();
            scrollToBottom(); // Scroll again after response/error
        }
    }

    async function regenerateLastResponse() {
         // Find the last user message and all messages before the last assistant message
         let lastUserMessageIndex = -1;
         let lastAssistantMessageIndex = -1;
         for (let i = messageHistory.length - 1; i >= 0; i--) {
              if (messageHistory[i].role === 'assistant' && lastAssistantMessageIndex === -1) {
                  lastAssistantMessageIndex = i;
              }
              if (messageHistory[i].role === 'user' && lastUserMessageIndex === -1) {
                  lastUserMessageIndex = i;
                   // If we found the last assistant message already, stop searching
                   if (lastAssistantMessageIndex !== -1) break;
              }
         }

         if (lastAssistantMessageIndex === -1) {
              showError("لا يوجد رد لإعادة توليده.");
              return;
         }

         // History up to (but not including) the last assistant message
         const historyForRegen = messageHistory.slice(0, lastAssistantMessageIndex);

        // Disable input and show indicator
        messageInput.disabled = true;
        sendButton.disabled = true;
        showTypingIndicator(true);
         // Maybe visually indicate which message is being regenerated? (optional)
         const lastAssistantBubble = messagesContainer.querySelector('.message-bubble.ai-bubble:last-of-type');
         if(lastAssistantBubble) lastAssistantBubble.style.opacity = '0.5';


        try {
            const response = await fetch('/api/regenerate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    conversation_id: currentConversationId,
                    model: modelSelect.value,
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value)
                    // Backend now gets history from DB based on conversation_id
                })
            });

            const data = await response.json();

            if (!response.ok) {
                 throw new Error(data.error || `HTTP error! status: ${response.status}`);
             }

            const regeneratedReply = data.reply;

            // Remove the old assistant message from UI and history
             if (lastAssistantBubble) lastAssistantBubble.remove();
             messageHistory.splice(lastAssistantMessageIndex, 1); // Remove from history array

            // Add the regenerated reply to UI and history
             addMessageToUI({ role: 'assistant', content: regeneratedReply }, data.backup_used, false); // Assuming regeneration is always online
             messageHistory.push({ role: 'assistant', content: regeneratedReply });

            showOfflineIndicator(false); // Should be online if successful

             // Update conversation timestamp
             updateConversationTimestamp(currentConversationId);

        } catch (error) {
             console.error("Error regenerating response:", error);
             addMessageToUI({ role: 'system', content: `فشل إعادة التوليد: ${error.message}` });
             showError(`فشل إعادة التوليد: ${error.message}`);
             if(lastAssistantBubble) lastAssistantBubble.style.opacity = '1'; // Restore opacity on error
        } finally {
            messageInput.disabled = false;
            sendButton.disabled = false;
            showTypingIndicator(false);
            messageInput.focus();
            scrollToBottom();
        }
    }

    function addWelcomeMessage() {
         const welcomeBubble = document.createElement('div');
         welcomeBubble.classList.add('message-bubble', 'ai-bubble', 'welcome-message');
         welcomeBubble.innerHTML = `
             <p>السلام عليكم! أنا ياسمين، مساعدتك الرقمية. كيف يمكنني المساعدة اليوم؟</p>
             <div class="message-actions">
                 <button class="copy-btn" title="نسخ الرد"><i class="fas fa-copy"></i></button>
                 <button class="speak-btn" title="قراءة الرد"><i class="fas fa-volume-up"></i></button>
             </div>
         `;
         messagesContainer.appendChild(welcomeBubble);
     }

     function addMessageToUI(message, backupUsed = false, offline = false, isError = false) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message-bubble');

        let contentHtml;
        // Sanitize and format message content (simple example)
        const sanitizedContent = escapeHtml(message.content);
        // Basic markdown-like formatting for newlines
        contentHtml = sanitizedContent.replace(/\n/g, '<br>');

        if (message.role === 'user') {
            messageElement.classList.add('user-bubble');
            messageElement.innerHTML = `<p>${contentHtml}</p>`; // No actions needed for user bubble initially
        } else if (message.role === 'assistant') {
            messageElement.classList.add('ai-bubble');
            let backupIndicator = backupUsed ? '<span class="backup-indicator" title="تم استخدام النموذج الاحتياطي (Gemini)">⚡️</span>' : '';
            let offlineIndicatorIcon = offline ? '<span class="offline-reply-indicator" title="رد في وضع عدم الاتصال">🌐</span>' : '';
             messageElement.innerHTML = `
                <p>${offlineIndicatorIcon}${backupIndicator}${contentHtml}</p>
                 <div class="message-actions">
                     <button class="copy-btn" title="نسخ الرد"><i class="fas fa-copy"></i></button>
                     <button class="speak-btn" title="قراءة الرد"><i class="fas fa-volume-up"></i></button>
                     ${!offline ? '<button class="regenerate-btn" title="إعادة توليد الرد"><i class="fas fa-sync-alt"></i></button>' : ''}
                 </div>
             `;
            // Speak the response if TTS is enabled
            if (isTTSEnabled && !offline) { // Don't speak offline predefined messages unless desired
                speakText(message.content);
            }
        } else if (message.role === 'system') { // For error messages
             messageElement.classList.add('error-message'); // Use a specific class
             messageElement.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${contentHtml}`;
         }

        messagesContainer.appendChild(messageElement);
        // Only scroll if the user hasn't scrolled up significantly
        // if (messagesContainer.scrollHeight - messagesContainer.scrollTop <= messagesContainer.clientHeight + 100) {
             scrollToBottom();
        // }
    }

    function handleMessageActionsClick(event) {
         const button = event.target.closest('button');
         if (!button) return;

         const messageBubble = button.closest('.message-bubble');
         if (!messageBubble) return;

         const messageContentElement = messageBubble.querySelector('p');
         const messageText = messageContentElement ? messageContentElement.innerText : ''; // Get raw text

         if (button.classList.contains('copy-btn')) {
             navigator.clipboard.writeText(messageText)
                 .then(() => {
                      // Optional: Show temporary feedback
                      const icon = button.querySelector('i');
                      icon.classList.replace('fa-copy', 'fa-check');
                      setTimeout(() => icon.classList.replace('fa-check', 'fa-copy'), 1500);
                 })
                 .catch(err => console.error('Failed to copy text: ', err));
         } else if (button.classList.contains('speak-btn')) {
             speakText(messageText);
         } else if (button.classList.contains('regenerate-btn')) {
              // Check if it's the *last* assistant message before allowing regenerate
              if (messageBubble.classList.contains('ai-bubble') && messageBubble === messagesContainer.querySelector('.ai-bubble:last-of-type')) {
                   regenerateLastResponse();
              } else {
                   showError("يمكن فقط إعادة توليد الرد الأخير.");
              }
         }
     }

     function updateConversationTimestamp(convId) {
          const item = conversationsList.querySelector(`.conversation-item[data-id="${convId}"]`);
          if (item) {
               // Move item to the top of the list visually
               conversationsList.prepend(item);
               // Optionally update a 'last updated' timestamp if displayed
          }
      }

    // --- Utility Functions ---

    function showTypingIndicator(show) {
        typingIndicator.style.display = show ? 'flex' : 'none';
         if(show) scrollToBottom(); // Scroll down when indicator appears
    }

    function showOfflineIndicator(show) {
         offlineIndicator.style.display = show ? 'block' : 'none';
     }

    function scrollToBottom() {
        // A small delay can sometimes help ensure rendering is complete
        setTimeout(() => {
             messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }, 50);
    }

    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        return unsafe
             .replace(/&/g, "&")
             .replace(/</g, "<")
             .replace(/>/g, ">")
             .replace(/"/g, """)
             .replace(/'/g, "'");
     }

     // --- Modal Functions ---
     function showConfirmModal(message, callback) {
          confirmMessage.textContent = message;
          confirmCallback = callback; // Store the action to perform on OK
          isDeleting = true; // Set flag
          confirmModal.classList.add('active');
      }

      function hideConfirmModal() {
          confirmModal.classList.remove('active');
          confirmCallback = null;
          isDeleting = false; // Reset flag
      }

      function handleConfirm() {
           if (confirmCallback) {
               confirmCallback();
           }
           hideConfirmModal();
       }

       function showError(message) {
           errorMessage.textContent = message;
           errorModal.classList.add('active');
       }

       function hideErrorModal() {
           errorModal.classList.remove('active');
       }


     // --- Text-to-Speech Functions ---
      function speakText(text) {
          if (!isTTSEnabled || !synth || !text) return;

          if (synth.speaking) {
              console.log('SpeechSynthesis.speaking: cancelling previous utterance.');
              synth.cancel(); // Cancel current speech if any
          }

          utterance.text = text;
          utterance.lang = 'ar-SA'; // Set language to Arabic (Saudi Arabia) - adjust if needed
          utterance.pitch = 1;
          utterance.rate = 1;
          utterance.volume = 0.8; // Adjust volume as needed

          // Optional: Log available voices to console for debugging
           // console.log("Available voices:", synth.getVoices());
           // const arabicVoice = synth.getVoices().find(voice => voice.lang === 'ar-SA');
           // if (arabicVoice) {
           //     utterance.voice = arabicVoice;
           // } else {
           //     console.warn("Arabic voice not found, using default.");
           // }


          utterance.onerror = (event) => {
              console.error('SpeechSynthesisUtterance.onerror', event);
              showError(`خطأ في نطق النص: ${event.error}`);
          };

          // Small delay before speaking, sometimes helps
          setTimeout(() => {
               synth.speak(utterance);
          }, 100);
      }

       // Ensure voices are loaded (needed on some browsers)
       if (speechSynthesis.onvoiceschanged !== undefined) {
            speechSynthesis.onvoiceschanged = () => { /* console.log("Voices loaded"); */ };
       }

}); // End DOMContentLoaded
