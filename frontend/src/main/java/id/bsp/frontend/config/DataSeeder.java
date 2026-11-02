package id.bsp.frontend.config;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.UserRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;

/**
 * Creates the first admin automatically on first run (if none exists); without it nobody could approve new users.
 *
 * <p>The password is not a fixed value in source (the repo is public). It is generated randomly ({@link SecureRandom}, 128 bit) and printed ONCE to the console; only its hash is stored, so recovery is a password reset. For automated installs it can be set via {@code nsm.seed-admin-password}.
 * This block runs only if the {@code users} table has no {@code admin} account.
 */
@Component
public class DataSeeder implements CommandLineRunner {

    private final UserRepository repo;
    private final PasswordEncoder encoder;

    /** First admin password if the operator wants to set it; empty (default) means random. */
    @Value("${nsm.seed-admin-password:}")
    private String sandiDitentukan;

    public DataSeeder(UserRepository repo, PasswordEncoder encoder) {
        this.repo = repo;
        this.encoder = encoder;
    }

    @Override
    public void run(String... args) {
        if (repo.findByUsername("admin").isPresent()) {
            return;
        }

        boolean acak = sandiDitentukan == null || sandiDitentukan.isBlank();
        String sandi = acak ? sandiAcak() : sandiDitentukan;

        User admin = new User();
        admin.setUsername("admin");
        admin.setEmail("admin@nsm.local");
        admin.setPassword(encoder.encode(sandi));
        admin.setRole("ADMIN");
        admin.setEnabled(true);
        admin.setCreatedAt(LocalDateTime.now());
        repo.save(admin);

        if (acak) {
            // Printed prominently and only once; afterwards the only copy is on the operator's screen.
            System.out.println();
            System.out.println("=".repeat(72));
            System.out.println(">>> NSM: akun admin pertama dibuat");
            System.out.println(">>>   username : admin");
            System.out.println(">>>   password : " + sandi);
            System.out.println(">>>");
            System.out.println(">>> Sandi ini DIBANGKITKAN ACAK dan TIDAK disimpan di mana pun.");
            System.out.println(">>> Salin sekarang, lalu ganti lewat halaman /account/password.");
            System.out.println("=".repeat(72));
            System.out.println();
        } else {
            System.out.println(">>> NSM: akun admin pertama dibuat dengan sandi dari "
                    + "'nsm.seed-admin-password'. Ganti setelah login pertama.");
        }
    }

    /**
     * 128 random bits from {@link SecureRandom}, URL-safe Base64 without padding: 22 characters that copy cleanly from any terminal.
     *
     * <p>Deliberately not a readable word, since easy-to-say defaults tend to survive.
     */
    private static String sandiAcak() {
        byte[] bita = new byte[16];
        new SecureRandom().nextBytes(bita);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bita);
    }
}
