package id.bsp.frontend.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/** One-time password reset token sent by email link. Expires after 30 minutes. */
@Entity
@Table(name = "password_reset_tokens")
public class PasswordResetToken {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // long random string (UUID) placed in the email link
    @Column(unique = true, nullable = false)
    private String token;

    // username pemilik token
    @Column(nullable = false)
    private String username;

    @Column(nullable = false)
    private LocalDateTime expiresAt;

    public PasswordResetToken() { }

    public PasswordResetToken(String token, String username, LocalDateTime expiresAt) {
        this.token = token;
        this.username = username;
        this.expiresAt = expiresAt;
    }

    public boolean isExpired() {
        return LocalDateTime.now().isAfter(expiresAt);
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getToken() { return token; }
    public void setToken(String token) { this.token = token; }

    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }

    public LocalDateTime getExpiresAt() { return expiresAt; }
    public void setExpiresAt(LocalDateTime expiresAt) { this.expiresAt = expiresAt; }
}
