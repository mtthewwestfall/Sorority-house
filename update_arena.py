with open('web/arena.html', 'r') as f:
    code = f.read()

old_draw = """function draw() {
      drawCastles(ctx, canvas.width, canvas.height);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#161b18";
      ctx.fillRect(0, 0, canvas.width, canvas.height);"""

new_draw = """function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#111412";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawCastles(ctx, canvas.width, canvas.height);"""

code = code.replace(old_draw, new_draw)

sprite_draw_old = """      // P1 Sprite
      ctx.fillStyle = p1.animState === 'hit' ? '#ff8080' : p1.isBlocking ? '#5cb85c' : '#D8B894';
      ctx.fillRect(p1.x, p1.y, p1.width, p1.height);
      ctx.fillStyle = "#E9E2D7";
      ctx.font = "12px sans-serif";
      ctx.fillText(`P1: ${p1Team[p1Index]?.name}`, p1.x - 10, p1.y - 10);

      // P2 Sprite
      ctx.fillStyle = p2.animState === 'hit' ? '#ffffff' : p2.isBlocking ? '#d9534f' : '#8A7D6B';
      ctx.fillRect(p2.x, p2.y, p2.width, p2.height);
      ctx.fillStyle = "#E9E2D7";
      ctx.fillText(`P2: ${p2Team[p2Index]?.name}`, p2.x - 10, p2.y - 10);"""

sprite_draw_new = """      // P1 Sprite & Tunic Overlay
      ctx.fillStyle = p1.animState === 'hit' ? '#ff8080' : p1.isBlocking ? '#5cb85c' : '#D8B894';
      ctx.fillRect(p1.x, p1.y, p1.width, p1.height);
      // Greek Tunic/Drapery overlay
      ctx.fillStyle = '#E9E2D7';
      ctx.fillRect(p1.x + 5, p1.y + 35, p1.width - 10, p1.height - 35);
      ctx.fillStyle = '#2F4A3C';
      ctx.fillRect(p1.x + 5, p1.y + 35, p1.width - 10, 6); // Tunic Sash
      ctx.fillStyle = '#D8B894';
      ctx.font = 'bold 12px serif';
      ctx.fillText(`P1: ${p1Team[p1Index]?.name}`, p1.x - 10, p1.y - 10);

      // P1 Dialogue Bubble
      if (p1Dialogue) {
        ctx.fillStyle = 'rgba(233,226,215,0.95)';
        ctx.fillRect(p1.x - 20, p1.y - 50, 150, 30);
        ctx.fillStyle = '#0d0f0e';
        ctx.font = '11px sans-serif';
        ctx.fillText(p1Dialogue, p1.x - 15, p1.y - 32);
      }

      // P2 Sprite & Tunic Overlay
      ctx.fillStyle = p2.animState === 'hit' ? '#ffffff' : p2.isBlocking ? '#d9534f' : '#8A7D6B';
      ctx.fillRect(p2.x, p2.y, p2.width, p2.height);
      // Roman/Greek Tunic overlay
      ctx.fillStyle = '#D8B894';
      ctx.fillRect(p2.x + 5, p2.y + 35, p2.width - 10, p2.height - 35);
      ctx.fillStyle = '#8A7D6B';
      ctx.fillRect(p2.x + 5, p2.y + 35, p2.width - 10, 6); // Tunic Sash
      ctx.fillStyle = '#E9E2D7';
      ctx.font = 'bold 12px serif';
      ctx.fillText(`P2: ${p2Team[p2Index]?.name}`, p2.x - 10, p2.y - 10);

      // P2 Dialogue Bubble
      if (p2Dialogue) {
        ctx.fillStyle = 'rgba(233,226,215,0.95)';
        ctx.fillRect(p2.x - 20, p2.y - 50, 150, 30);
        ctx.fillStyle = '#0d0f0e';
        ctx.font = '11px sans-serif';
        ctx.fillText(p2Dialogue, p2.x - 15, p2.y - 32);
      }"""

code = code.replace(sprite_draw_old, sprite_draw_new)

if 'let p1Dialogue' not in code:
    code = code.replace('let gameOver = false;', 'let gameOver = false;\n    let p1Dialogue = "For God\'s Greek!";\n    let p2Dialogue = "Defend the Realm!";')

with open('web/arena.html', 'w') as f:
    f.write(code)

print("Updated web/arena.html cleanly.")
