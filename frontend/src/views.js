const noop = () => {};

export const views = {
  renderTranscript: noop,
  updateReviewUI: noop,
  gotoTypo: noop,
  resetReview: noop,
  nextPending: () => -1,
  renderSnapshot: noop,
  renderTermCandidates: noop,
  assistantStatus: noop,
  deskStatus: noop,
  showAuth: noop,
};

export const actions = {
  confirm() {},
  reproof() {},
  summarize() {},
  openMeeting() {},
};
