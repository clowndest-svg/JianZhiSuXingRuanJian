package com.fitcoach.shapemaster;

/**
 * 更新弹窗的正文。单独放一个类是因为它只是字符串排版，不该绑在 Android 运行时上——
 * 纯 Java 才能在本机 javac + java 真跑一遍，判据也不用停在"看着像对的"。
 */
public final class UpdateCopy {

    private UpdateCopy() {
    }

    public static String body(int mine, int remote, String sizeText, String notes) {
        StringBuilder sb = new StringBuilder();
        sb.append("当前 ").append(mine).append(" 版 → 最新 ").append(remote).append(" 版\n");
        sb.append("安装包约 ").append(sizeText).append("，下载会交给系统浏览器。");
        String detail = detail(notes);
        sb.append("\n\n");
        if (detail.length() == 0) {
            sb.append("这一版没有写更新说明。");
        } else {
            sb.append(detail);
        }
        sb.append("\n\n安装仍需要你在系统设置里放行。");
        return sb.toString();
    }

    /**
     * 清单里的 notes 来自 CHANGELOG：首行是"r157 / 2.0.9（41）"这种工程标题，
     * 弹窗标题栏已经写了版本号，正文再重复一遍就像日志，所以丢掉它。
     */
    public static String detail(String notes) {
        String clean = notes == null ? "" : notes.trim();
        String[] lines = clean.split("\n");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].trim();
            if (i == 0 && line.matches("^r\\d+\\s*/.*")) {
                continue;
            }
            if (line.isEmpty()) {
                if (out.length() > 0 && out.charAt(out.length() - 1) != '\n') {
                    out.append('\n');
                }
                continue;
            }
            if (out.length() > 0 && out.charAt(out.length() - 1) != '\n') {
                out.append('\n');
            }
            out.append(line);
        }
        return out.toString().trim();
    }
}
