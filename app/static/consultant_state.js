(function (root, factory) {
  const value = factory();
  if (typeof module === "object" && module.exports) module.exports = value;
  else root.ConsultantStateStore = value;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const validMessage = message => Boolean(
    message && typeof message === "object" &&
    (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string"
  );

  const validMessages = messages => Array.isArray(messages) ? messages.filter(validMessage) : [];

  class ConsultantStateStore {
    constructor() { this.states = new Map(); this.active = null; }
    ensure(chatId) {
      if (!this.states.has(chatId)) this.states.set(chatId, {
        messages: [], loading: false, retryId: null, editing: null, draft: "",
        error: "", operation: 0, loadGeneration: 0, deleted: false, deleting: false,
        historyLoaded: false, historyLoading: false, lastMessageId: null,
        historyAbort: null, historyRequests: 0, historyFetchedAt: 0,
      });
      const state = this.states.get(chatId);
      // Sanitize states created by an older script and all data which crossed an async boundary.
      // This also heals a currently open page after one malformed provider/history response.
      state.messages = validMessages(state.messages);
      return state;
    }
    select(chatId) { this.active = chatId; return this.ensure(chatId); }
    activeState() { return this.active ? this.ensure(this.active) : null; }
    hasFreshHistory(chatId, lastMessageId, maxAgeMs = 5000) {
      const state = this.ensure(chatId);
      return state.historyLoaded && state.lastMessageId === lastMessageId &&
        Date.now() - state.historyFetchedAt <= maxAgeMs;
    }
    beginLoad(chatId) { const state = this.ensure(chatId); return ++state.loadGeneration; }
    beginHistory(chatId) {
      const state = this.ensure(chatId);
      if (state.historyLoading || state.deleted) return null;
      state.historyLoading = true; state.historyRequests += 1;
      return ++state.loadGeneration;
    }
    finishHistory(chatId, generation) {
      const state = this.states.get(chatId);
      if (!state || generation !== state.loadGeneration) return false;
      state.historyLoading = false; state.historyAbort = null; return true;
    }
    cancelHistory(chatId) {
      const state = this.states.get(chatId); if (!state) return;
      state.historyAbort?.abort(); state.historyAbort = null; state.historyLoading = false;
      state.loadGeneration += 1;
    }
    applyLoad(chatId, generation, messages, lastMessageId = null) {
      const state = this.states.get(chatId);
      if (!state || state.deleted || state.loading || generation !== state.loadGeneration) return false;
      state.messages = validMessages(messages); state.historyLoaded = true; state.historyLoading = false;
      state.lastMessageId = lastMessageId; state.historyFetchedAt = Date.now(); return true;
    }
    setMessages(chatId, messages) {
      const state = this.ensure(chatId); state.messages = validMessages(messages); return state.messages;
    }
    appendMessage(chatId, message) {
      if (!validMessage(message)) return false;
      this.ensure(chatId).messages.push(message); return true;
    }
    beginOperation(chatId) {
      const state = this.ensure(chatId);
      if (state.loading || state.deleted || state.deleting) return null;
      // A send/edit supersedes a history snapshot which may already be in flight. Abort that
      // snapshot here (not merely because the user navigated away) so an older response cannot
      // replace the optimistic message or the regenerated branch.
      if (state.historyLoading) {
        state.historyAbort?.abort(); state.historyAbort = null;
        state.historyLoading = false; state.loadGeneration += 1;
      }
      state.loading = true; state.error = ""; return ++state.operation;
    }
    isCurrent(chatId, operation) {
      const state = this.states.get(chatId);
      return Boolean(state && !state.deleted && state.operation === operation);
    }
    finishOperation(chatId, operation) {
      if (!this.isCurrent(chatId, operation)) return false;
      this.states.get(chatId).loading = false; return true;
    }
    remove(chatId) {
      const state = this.states.get(chatId);
      if (state) { this.cancelHistory(chatId); state.deleted = true; state.operation += 1; }
      this.states.delete(chatId); if (this.active === chatId) this.active = null;
    }
  }
  ConsultantStateStore.validMessage = validMessage;
  ConsultantStateStore.validMessages = validMessages;
  return ConsultantStateStore;
});
