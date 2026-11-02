package id.bsp.frontend.controller;

import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.security.SecureRandom;

/** Local (offline) CAPTCHA. The image is drawn with Java2D, with no external library or third party. The code is kept in the server session, checked at sign-up (see AuthController), and single use. */
@Controller
public class CaptchaController {

    /** Session attribute name holding the captcha answer. */
    public static final String SESSION_KEY = "NSM_CAPTCHA";

    // Hindari karakter ambigu: 0/O, 1/I/L
    private static final String CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
    private static final int LEN = 5;
    private final SecureRandom rnd = new SecureRandom();

    @GetMapping("/captcha")
    public void captcha(HttpSession session, HttpServletResponse resp) throws IOException {
        // 1) generate a random code and store it in the session
        StringBuilder code = new StringBuilder();
        for (int i = 0; i < LEN; i++) {
            code.append(CHARS.charAt(rnd.nextInt(CHARS.length())));
        }
        session.setAttribute(SESSION_KEY, code.toString());

        // 2) draw the code onto an image with distortion and noise
        int w = 170, h = 50;
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);

        // background terang
        g.setColor(new Color(238, 238, 238));
        g.fillRect(0, 0, w, h);

        // garis-garis noise
        for (int i = 0; i < 8; i++) {
            g.setColor(new Color(rnd.nextInt(180) + 40, rnd.nextInt(180) + 40, rnd.nextInt(180) + 40));
            g.drawLine(rnd.nextInt(w), rnd.nextInt(h), rnd.nextInt(w), rnd.nextInt(h));
        }

        for (int i = 0; i < code.length(); i++) {
            g.setColor(new Color(rnd.nextInt(110), rnd.nextInt(110), rnd.nextInt(110)));
            g.setFont(new Font("Arial", Font.BOLD, 30 + rnd.nextInt(6)));
            double angle = (rnd.nextDouble() - 0.5) * 0.6;
            int x = 16 + i * 30;
            int y = 34 + (rnd.nextInt(7) - 3);
            g.rotate(angle, x, y);
            g.drawString(String.valueOf(code.charAt(i)), x, y);
            g.rotate(-angle, x, y);
        }

        // titik-titik noise
        for (int i = 0; i < 45; i++) {
            g.setColor(new Color(rnd.nextInt(256), rnd.nextInt(256), rnd.nextInt(256)));
            g.fillOval(rnd.nextInt(w), rnd.nextInt(h), 2, 2);
        }
        g.dispose();

        // 3) send as PNG; no caching, so every load gets a new captcha
        resp.setContentType("image/png");
        resp.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
        resp.setHeader("Pragma", "no-cache");
        ImageIO.write(img, "png", resp.getOutputStream());
    }
}
