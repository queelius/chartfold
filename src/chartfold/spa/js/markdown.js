const Markdown = {
  render(text) {
    return '<p>' + (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>') + '</p>';
  }
};
