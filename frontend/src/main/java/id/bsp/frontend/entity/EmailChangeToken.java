package id.bsp.frontend.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * One-time token for verifying an email change. Like PasswordResetToken but also stores the
 * requested new email; the account email changes only when the link is clicked from the new
 * inbox. Expires after 30 minutes.
 */
@Entity
@Table(name = "email_change_tokens")
public class EmailChangeToken {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String token;

    @Column(nullable = false)
    private String username;

    @Column(name = "new_email", nullable = false)
    private String newEmail;

    @Column(nullable = false)
    private LocalDateTime expiresAt;

    public EmailChangeToken() { }

    public EmailChangeToken(String token, String username, String newEmail,
                            LocalDateTime expiresAt) {
        this.token = token;
        this.username = username;
        this.newEmail = newEmail;
        this.expiresAt = expiresAt;
    }

    public boolean isExpired() {
        return LocalDateTime.now().isAfter(expiresAt);
    }

    public Long getId() { return id; }
    public String getToken() { return token; }
    public String getUsername() { return username; }
    public String getNewEmail() { return newEmail; }
    public LocalDateTime getExpiresAt() { return expiresAt; }
}
