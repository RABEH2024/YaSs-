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
    let currentConversationId = generateId(); // Default conversation ID
    let currentModel = 'mistralai/mistral-7b-instruct'; // Default model
    let conversations = {}; // To store conversations data
    let isSendingMessage = false; // Flag to prevent multiple sends
    let confirmCallback = null; // For the confirm modal

    // --- Initialize App ---
    loadSettings();
    loadConversations();
    loadModels();
    checkOnlineStatus();

    // Listen for network status changes
    window.addEventListener('online', handleOnlineStatusChange);
    window.addEventListener('offline', handleOnlineStatusChange);

    // --- Event Listeners ---
    
    // Send message on button click
    sendButton.addEventListener('click', sendMessage);
    
    // Send message on Enter (but allow Shift+Enter for new line)
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Update temperature value display when slider changes
    temperatureSlider.addEventListener('input', function() {
        temperatureValue.textContent = this.value;
        saveSettings();
    });
    
    // Save settings when they change
    modelSelect.addEventListener('change', function() {
        currentModel = this.value;
        saveSettings();
    });
    
    maxTokensInput.addEventListener('change', saveSettings);
    
    // Toggle dark mode
    darkModeToggle.addEventListener('change', function() {
        document.body.classList.toggle('dark-mode', this.checked);
        saveSettings();
    });
    
    // Toggle TTS
    ttsToggle.addEventListener('change', saveSettings);
    
    // New conversation button
    newConversationBtn.addEventListener('click', createNewConversation);
    
    // Modal buttons
    confirmOkBtn.addEventListener('click', function() {
        if (confirmCallback) confirmCallback();
        hideModal();
    });
    
    confirmCancelBtn.addEventListener('click', hideModal);
    
    // Mobile menu buttons
    mobileMenuBtn.addEventListener('click', toggleSidebar);
    mobileSettingsBtn.addEventListener('click', toggleSidebar);
    toggleSidebarBtn.addEventListener('click', toggleSidebar);

    // --- Functions ---
    
    // Send message to the AI
    function sendMessage() {
        const message = messageInput.value.trim();
        if (!message || isSendingMessage) return;
        
        // Get current conversation or create new one
        if (!conversations[currentConversationId]) {
            conversations[currentConversationId] = {
                id: currentConversationId,
                title: extractTitle(message),
                messages: []
            };
        }
        
        // Add user message to UI
        addMessageToUI('user', message);
        
        // Add to conversation history
        conversations[currentConversationId].messages.push({
            role: 'user',
            content: message
        });
        
        // Clear input and save
        messageInput.value = '';
        saveConversations();
        updateConversationsList();
        
        // Show typing indicator
        const typingIndicator = document.createElement('div');
        typingIndicator.className = 'typing-indicator';
        typingIndicator.textContent = 'ياسمين تكتب...';
        messagesContainer.appendChild(typingIndicator);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        
        // Set flag to prevent multiple sends
        isSendingMessage = true;
        
        // Call the API
        callChatAPI(message)
            .then(response => {
                // Remove typing indicator
                if (typingIndicator.parentNode) {
                    typingIndicator.parentNode.removeChild(typingIndicator);
                }
                
                if (response.error) {
                    // Handle errors
                    addMessageToUI('ai', `عذراً، حدث خطأ: ${response.error}`);
                } else {
                    // Add AI response to UI
                    addMessageToUI('ai', response.reply, true);
                    
                    // Add to conversation history
                    conversations[currentConversationId].messages.push({
                        role: 'assistant',
                        content: response.reply
                    });
                    
                    // If this is the first message, update the conversation title
                    if (conversations[currentConversationId].messages.length === 2) {
                        conversations[currentConversationId].title = extractTitle(message);
                        updateConversationsList();
                    }
                    
                    // Save conversations
                    saveConversations();
                    
                    // Speak the response if TTS is enabled
                    if (ttsToggle.checked) {
                        speakText(response.reply);
                    }
                }
            })
            .catch(error => {
                // Remove typing indicator
                if (typingIndicator.parentNode) {
                    typingIndicator.parentNode.removeChild(typingIndicator);
                }
                
                console.error('Error:', error);
                addMessageToUI('ai', 'عذراً، حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى.');
            })
            .finally(() => {
                // Reset flag
                isSendingMessage = false;
            });
    }
    
    // Call the Chat API
    async function callChatAPI(message) {
        // Check if online
        if (!navigator.onLine) {
            // Check for offline responses
            for (const keyword in offlineResponses) {
                if (message.toLowerCase().includes(keyword)) {
                    return { reply: offlineResponses[keyword], offline: true };
                }
            }
            return { reply: "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت.", offline: true };
        }
        
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: message,
                    model: currentModel,
                    history: conversations[currentConversationId]?.messages || [],
                    conversation_id: currentConversationId,
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value)
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API call error:', error);
            return { error: error.message };
        }
    }
    
    // Regenerate the last AI response
    async function regenerateResponse(messageElement) {
        if (isSendingMessage) return;
        
        // Get the conversation up to the message before this one
        const conversation = conversations[currentConversationId];
        if (!conversation) return;
        
        // Find the index of the message to regenerate
        const messageIndex = Array.from(messagesContainer.children).indexOf(messageElement);
        if (messageIndex === -1) return;
        
        // Get all messages up to the user message before this AI message
        const messages = conversation.messages.slice(0, conversation.messages.length - 1);
        
        // Show typing indicator
        const typingIndicator = document.createElement('div');
        typingIndicator.className = 'typing-indicator';
        typingIndicator.textContent = 'ياسمين تكتب...';
        messageElement.parentNode.insertBefore(typingIndicator, messageElement.nextSibling);
        
        // Remove the old AI message
        messageElement.style.opacity = '0.5';
        
        // Set flag to prevent multiple sends
        isSendingMessage = true;
        
        try {
            const response = await fetch('/api/regenerate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    messages: messages,
                    model: currentModel,
                    conversation_id: currentConversationId,
                    temperature: parseFloat(temperatureSlider.value),
                    max_tokens: parseInt(maxTokensInput.value)
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            
            const result = await response.json();
            
            // Remove typing indicator
            if (typingIndicator.parentNode) {
                typingIndicator.parentNode.removeChild(typingIndicator);
            }
            
            // Update the AI message content
            const contentElement = messageElement.querySelector('p');
            if (contentElement) {
                contentElement.textContent = result.reply;
            }
            
            // Update in conversation history
            conversations[currentConversationId].messages[conversation.messages.length - 1] = {
                role: 'assistant',
                content: result.reply
            };
            
            // Save conversations
            saveConversations();
            
            // Reset message style
            messageElement.style.opacity = '1';
            
            // Speak the response if TTS is enabled
            if (ttsToggle.checked) {
                speakText(result.reply);
            }
        } catch (error) {
            // Remove typing indicator
            if (typingIndicator.parentNode) {
                typingIndicator.parentNode.removeChild(typingIndicator);
            }
            
            console.error('Regenerate error:', error);
            // Reset message style
            messageElement.style.opacity = '1';
            
            // Show error
            addMessageToUI('ai', 'عذراً، حدث خطأ أثناء إعادة التوليد. يرجى المحاولة مرة أخرى.');
        } finally {
            // Reset flag
            isSendingMessage = false;
        }
    }
    
    // Add a message to the UI
    function addMessageToUI(role, content, isAI = false) {
        const bubble = document.createElement('div');
        bubble.className = `message-bubble ${role}-bubble`;
        
        const text = document.createElement('p');
        text.textContent = content;
        bubble.appendChild(text);
        
        // Add action buttons
        const actions = document.createElement('div');
        actions.className = 'message-actions';
        
        // Add copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.title = 'نسخ';
        copyBtn.innerHTML = '<i class="fas fa-copy"></i>';
        copyBtn.addEventListener('click', () => copyToClipboard(content));
        actions.appendChild(copyBtn);
        
        // Add regenerate button for AI messages
        if (isAI) {
            const regenerateBtn = document.createElement('button');
            regenerateBtn.className = 'regenerate-btn';
            regenerateBtn.title = 'إعادة التوليد';
            regenerateBtn.innerHTML = '<i class="fas fa-redo-alt"></i>';
            regenerateBtn.addEventListener('click', () => regenerateResponse(bubble));
            actions.appendChild(regenerateBtn);
            
            // Add speak button
            const speakBtn = document.createElement('button');
            speakBtn.className = 'speak-btn';
            speakBtn.title = 'استماع';
            speakBtn.innerHTML = '<i class="fas fa-volume-up"></i>';
            speakBtn.addEventListener('click', () => speakText(content));
            actions.appendChild(speakBtn);
        }
        
        bubble.appendChild(actions);
        messagesContainer.appendChild(bubble);
        
        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    
    // Load messages for a conversation
    function loadConversationMessages(conversationId) {
        // Clear messages container
        messagesContainer.innerHTML = '';
        
        // If no conversation, add welcome message
        if (!conversations[conversationId] || conversations[conversationId].messages.length === 0) {
            addMessageToUI('ai', 'السلام عليكم! أنا ياسمين، مساعدتك الرقمية بالعربية. كيف يمكنني مساعدتك اليوم؟', true);
            return;
        }
        
        // Add all messages
        conversations[conversationId].messages.forEach(msg => {
            addMessageToUI(msg.role === 'user' ? 'user' : 'ai', msg.content, msg.role === 'assistant');
        });
    }
    
    // Create a new conversation
    function createNewConversation() {
        currentConversationId = generateId();
        conversations[currentConversationId] = {
            id: currentConversationId,
            title: 'محادثة جديدة',
            messages: []
        };
        
        saveConversations();
        updateConversationsList();
        loadConversationMessages(currentConversationId);
        
        // Close sidebar on mobile
        if (window.innerWidth <= 768) {
            sidebar.classList.remove('active');
        }
    }
    
    // Switch to a conversation
    function switchConversation(conversationId) {
        if (conversationId === currentConversationId) return;
        
        currentConversationId = conversationId;
        loadConversationMessages(conversationId);
        
        // Update active class in the list
        const items = conversationsList.querySelectorAll('.conversation-item');
        items.forEach(item => {
            item.classList.toggle('active', item.dataset.id === conversationId);
        });
        
        // Close sidebar on mobile
        if (window.innerWidth <= 768) {
            sidebar.classList.remove('active');
        }
    }
    
    // Delete a conversation
    function deleteConversation(conversationId) {
        confirmMessage.textContent = 'هل أنت متأكد من أنك تريد حذف هذه المحادثة؟';
        showModal(() => {
            delete conversations[conversationId];
            saveConversations();
            
            // If current conversation was deleted, create a new one
            if (conversationId === currentConversationId) {
                createNewConversation();
            } else {
                updateConversationsList();
            }
        });
    }
    
    // Update the conversations list in the sidebar
    function updateConversationsList() {
        conversationsList.innerHTML = '';
        
        const conversationIds = Object.keys(conversations);
        
        if (conversationIds.length === 0) {
            const emptyState = document.createElement('div');
            emptyState.className = 'empty-state';
            emptyState.textContent = 'لا توجد محادثات سابقة';
            conversationsList.appendChild(emptyState);
            return;
        }
        
        // Sort by newest first (assuming we add timestamp later)
        conversationIds.forEach(id => {
            const conversation = conversations[id];
            const item = document.createElement('div');
            item.className = 'conversation-item';
            if (id === currentConversationId) {
                item.classList.add('active');
            }
            item.dataset.id = id;
            
            const title = document.createElement('span');
            title.textContent = conversation.title || 'محادثة جديدة';
            item.appendChild(title);
            
            const actions = document.createElement('div');
            actions.className = 'conversation-actions';
            
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-btn';
            deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteConversation(id);
            });
            actions.appendChild(deleteBtn);
            
            item.appendChild(actions);
            
            item.addEventListener('click', () => switchConversation(id));
            conversationsList.appendChild(item);
        });
    }
    
    // Load available models from API
    async function loadModels() {
        try {
            const response = await fetch('/api/models');
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            
            const data = await response.json();
            
            // Clear select options
            modelSelect.innerHTML = '';
            
            // Add options
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.name;
                modelSelect.appendChild(option);
            });
            
            // Set current model
            modelSelect.value = currentModel;
        } catch (error) {
            console.error('Error loading models:', error);
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
        
        // Update current model
        currentModel = modelSelect.value;
    }
    
    // Load app settings from localStorage
    function loadSettings() {
        const settings = JSON.parse(localStorage.getItem('yasminSettings'));
        
        if (settings) {
            // Apply dark mode
            darkModeToggle.checked = settings.darkMode;
            document.body.classList.toggle('dark-mode', settings.darkMode);
            
            // Apply other settings
            ttsToggle.checked = settings.ttsEnabled || false;
            temperatureSlider.value = settings.temperature || 0.7;
            temperatureValue.textContent = temperatureSlider.value;
            maxTokensInput.value = settings.maxTokens || 512;
            
            // Set current model
            if (settings.model) {
                currentModel = settings.model;
                // We'll set the select value when models are loaded
            }
        }
    }
    
    // Save conversations to localStorage
    function saveConversations() {
        localStorage.setItem('yasminConversations', JSON.stringify(conversations));
    }
    
    // Load conversations from localStorage
    function loadConversations() {
        const savedConversations = JSON.parse(localStorage.getItem('yasminConversations'));
        
        if (savedConversations && Object.keys(savedConversations).length > 0) {
            conversations = savedConversations;
            currentConversationId = Object.keys(conversations)[0]; // Load first conversation
        } else {
            // Create default conversation
            currentConversationId = generateId();
            conversations[currentConversationId] = {
                id: currentConversationId,
                title: 'محادثة جديدة',
                messages: []
            };
        }
        
        updateConversationsList();
        loadConversationMessages(currentConversationId);
    }
    
    // Copy text to clipboard
    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(() => {
            // Show a brief notification (could be improved)
            const notification = document.createElement('div');
            notification.style.position = 'fixed';
            notification.style.bottom = '20px';
            notification.style.right = '50%';
            notification.style.transform = 'translateX(50%)';
            notification.style.background = '#4CAF50';
            notification.style.color = 'white';
            notification.style.padding = '10px 20px';
            notification.style.borderRadius = '5px';
            notification.style.zIndex = '1000';
            notification.textContent = 'تم النسخ!';
            
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.style.opacity = '0';
                notification.style.transition = 'opacity 0.5s';
                setTimeout(() => {
                    document.body.removeChild(notification);
                }, 500);
            }, 1500);
        }).catch(err => {
            console.error('Failed to copy text: ', err);
        });
    }
    
    // Text-to-speech function
    function speakText(text) {
        if ('speechSynthesis' in window) {
            // Cancel any ongoing speech
            window.speechSynthesis.cancel();
            
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'ar-SA'; // Arabic language
            
            // Get available voices
            let voices = speechSynthesis.getVoices();
            
            // If voices list is empty, wait for the voiceschanged event
            if (voices.length === 0) {
                speechSynthesis.addEventListener('voiceschanged', () => {
                    voices = speechSynthesis.getVoices();
                    setVoice();
                });
            } else {
                setVoice();
            }
            
            function setVoice() {
                // Try to find an Arabic voice
                const arabicVoice = voices.find(voice => 
                    voice.lang.includes('ar') || 
                    voice.name.includes('Arabic')
                );
                
                if (arabicVoice) {
                    utterance.voice = arabicVoice;
                }
                
                window.speechSynthesis.speak(utterance);
            }
        }
    }
    
    // Check online status
    function checkOnlineStatus() {
        if (navigator.onLine) {
            offlineIndicator.style.display = 'none';
        } else {
            offlineIndicator.style.display = 'block';
        }
    }
    
    // Handle online status change
    function handleOnlineStatusChange() {
        checkOnlineStatus();
    }
    
    // Toggle sidebar on mobile
    function toggleSidebar() {
        sidebar.classList.toggle('active');
    }
    
    // Show confirmation modal
    function showModal(callback) {
        confirmModal.style.display = 'flex';
        confirmCallback = callback;
    }
    
    // Hide confirmation modal
    function hideModal() {
        confirmModal.style.display = 'none';
        confirmCallback = null;
    }
    
    // Generate a unique ID
    function generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2);
    }
    
    // Extract a title from the first message
    function extractTitle(message) {
        // Get first 20 characters or less
        let title = message.substring(0, 20).trim();
        if (message.length > 20) {
            title += '...';
        }
        return title;
    }
    
    // Offline responses for common greetings
    const offlineResponses = {
        "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حاليًا.",
        "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
        "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
        "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
        "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
    };
});
