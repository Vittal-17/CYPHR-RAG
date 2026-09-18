## 2024-03-24 - Missing Loading States for Async Operations
**Learning:** Found that the app's component architecture frequently omitted loading states for asynchronous operations (like creating a new chat or deleting a chat). This lack of visual feedback on button clicks can confuse users and lead to double-clicks or uncertainty about background processes.
**Action:** Always verify that interactive elements triggering async requests provide immediate visual feedback (e.g. disabling the button and showing a spinner like `Loader2`) to improve the perceived performance and reliability.
