package id.bsp.frontend.security;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.UserRepository;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

/**
 * Loads users from the database for Spring Security. enabled=false (pending) is rejected
 * automatically; a future `lockedUntil` marks the account as locked and rejects login.
 */
@Service
public class CustomUserDetailsService implements UserDetailsService {

    private final UserRepository repo;

    public CustomUserDetailsService(UserRepository repo) {
        this.repo = repo;
    }

    @Override
    public UserDetails loadUserByUsername(String username) {
        User u = repo.findByUsername(username)
                .orElseThrow(() -> new UsernameNotFoundException("User tidak ditemukan: " + username));

        boolean locked = u.getLockedUntil() != null
                && u.getLockedUntil().isAfter(java.time.LocalDateTime.now());

        return org.springframework.security.core.userdetails.User
                .withUsername(u.getUsername())
                .password(u.getPassword())     // hash bcrypt
                .roles(u.getRole())            // "ADMIN" -> ROLE_ADMIN
                .disabled(!u.isEnabled())      // pending = disabled -> login ditolak
                .accountLocked(locked)         // terkunci sementara -> login ditolak
                .build();
    }
}
