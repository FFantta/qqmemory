import AppKit

// Finder uses a static background; the actual drag/copy uses macOS animations.
let canvas = NSSize(width: 720, height: 480)
let image = NSImage(size: canvas)
image.lockFocus()
NSColor(calibratedRed: 0.96, green: 0.95, blue: 0.92, alpha: 1).setFill()
NSBezierPath(rect: NSRect(origin: .zero, size: canvas)).fill()
func text(_ value: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat, _ color: NSColor) {
    (value as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [
        .font: NSFont.systemFont(ofSize: size), .foregroundColor: color
    ])
}
let ink = NSColor(calibratedWhite: 0.22, alpha: 1)
let muted = NSColor(calibratedWhite: 0.42, alpha: 1)
text("空间记忆", 44, 416, 28, ink)
text("将左侧应用拖入右侧「应用程序」", 44, 382, 16, muted)
text("→", 328, 252, 48, NSColor(calibratedRed: 0.40, green: 0.49, blue: 0.43, alpha: 1))
NSColor(calibratedWhite: 0.80, alpha: 1).setStroke()
let rule = NSBezierPath()
rule.move(to: NSPoint(x: 44, y: 166)); rule.line(to: NSPoint(x: 676, y: 166)); rule.stroke()
text("首次打开", 44, 130, 17, ink)
text("安装后，从「应用程序」打开空间记忆。", 44, 101, 14, muted)
text("若提示无法验证开发者，请先尝试打开一次，再前往：", 44, 75, 14, muted)
text("系统设置 → 隐私与安全性 → 仍要打开", 44, 49, 15, ink)
text("仅在确认下载来源可信时允许；无需关闭系统安全保护。", 44, 22, 12, muted)
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
