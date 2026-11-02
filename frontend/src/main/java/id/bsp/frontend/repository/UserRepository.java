package id.bsp.frontend.repository;

import id.bsp.frontend.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByUsername(String username);

    Optional<User> findByEmail(String email);

    boolean existsByUsername(String username);

    boolean existsByEmail(String email);

    // Accounts awaiting admin approval. `nonaktif` must be filtered too: revoked accounts also have
    // enabled=false and would otherwise show up as new sign-ups with an Approve button.
    List<User> findByEnabledFalseAndNonaktifFalse();

    // Device alert recipients: all approved accounts.
    List<User> findByEnabledTrue();

    // Number of admins who can still log in; guards against revoking the last admin.
    long countByRoleAndEnabledTrue(String role);
}
