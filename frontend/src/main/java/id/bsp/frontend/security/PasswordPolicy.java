package id.bsp.frontend.security;

import java.util.Set;

/**
 * Central password policy: at least 8 characters, upper case, lower case and a digit, not a
 * common password, and not containing the username. `validate()` returns null on success or an
 * error message (in Indonesian) on failure.
 */
public final class PasswordPolicy {

    private PasswordPolicy() { }

    public static final int MIN_LENGTH = 8;

    /** Most common passwords to reject (lowercase). */
    private static final Set<String> COMMON = Set.of(
        "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
        "qwerty", "qwerty123", "qwertyuiop", "111111", "000000", "abc12345",
        "iloveyou", "admin123", "administrator", "letmein", "welcome", "welcome1",
        "monkey", "dragon", "sunshine", "princess", "football", "baseball",
        "superman", "michael", "asdfghjkl", "zxcvbnm", "1q2w3e4r", "1qaz2wsx"
    );

    /**
     * @param password candidate password (plaintext, only checked then discarded)
     * @param username the user's username (to reject passwords containing it)
     * @return null if acceptable, otherwise the first error message found
     */
    public static String validate(String password, String username) {
        if (password == null || password.length() < MIN_LENGTH) {
            return "Password minimal " + MIN_LENGTH + " karakter.";
        }
        if (!password.matches(".*[A-Z].*")) {
            return "Password harus mengandung minimal 1 huruf besar.";
        }
        if (!password.matches(".*[a-z].*")) {
            return "Password harus mengandung minimal 1 huruf kecil.";
        }
        if (!password.matches(".*[0-9].*")) {
            return "Password harus mengandung minimal 1 angka.";
        }
        if (COMMON.contains(password.toLowerCase())) {
            return "Password terlalu umum, pilih yang lain.";
        }
        if (username != null && !username.isBlank()
                && password.toLowerCase().contains(username.toLowerCase())) {
            return "Password tidak boleh mengandung username.";
        }
        return null;
    }
}
