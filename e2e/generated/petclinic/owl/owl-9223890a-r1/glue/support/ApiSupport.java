package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiSupport {

    private static final String LETTERS = "abcdefghijklmnopqrstuvwxyz";

    private ApiSupport() {
    }

    public static int randomInt(int minInclusive, int maxInclusive) {
        return ThreadLocalRandom.current().nextInt(minInclusive, maxInclusive + 1);
    }

    public static String randomLetters(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append(LETTERS.charAt(randomInt(0, LETTERS.length() - 1)));
        }
        return sb.toString();
    }

    public static String randomDigits(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append(randomInt(0, 9));
        }
        return sb.toString();
    }

    public static String uniqueName(String prefix) {
        return prefix + randomLetters(8);
    }

    public static String futureDate(int minDays, int maxDays) {
        return LocalDate.now().plusDays(randomInt(minDays, maxDays)).toString();
    }

    public static String pastDate(int daysAgo) {
        return LocalDate.now().minusDays(daysAgo).toString();
    }

    public static String plusDays(String isoDate, int days) {
        return LocalDate.parse(isoDate).plusDays(days).toString();
    }

    public static Map<String, Object> reservation(String petName, int roomNumber, int nights, int animalCount,
            String checkInDate, String promoCode) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("petName", petName);
        body.put("ownerEmail", petName.trim().toLowerCase() + "@example.com");
        body.put("roomNumber", roomNumber);
        body.put("nights", nights);
        body.put("animalCount", animalCount);
        body.put("checkInDate", checkInDate);
        if (promoCode != null) {
            body.put("promoCode", promoCode);
        }
        return body;
    }

    public static Map<String, Object> randomReservation(int nights) {
        return reservation(uniqueName("Pet"), randomInt(1, 9), nights, 1, futureDate(30, 330), null);
    }

    public static Map<String, Object> owner(String firstName, String lastName, String address, String city,
            String telephone) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("firstName", firstName);
        body.put("lastName", lastName);
        body.put("address", address);
        body.put("city", city);
        body.put("telephone", telephone);
        return body;
    }

    public static Map<String, Object> randomOwner() {
        return owner(uniqueName("Ann"), uniqueName("Lee"), randomDigits(3) + " " + uniqueName("Oak") + " Street",
                uniqueName("City"), randomDigits(10));
    }

    public static String text(Response response) {
        String body = response.asString();
        return body == null ? "" : body;
    }

    public static Object field(Response response, String path) {
        if (text(response).isBlank()) {
            return null;
        }
        try {
            return response.jsonPath().get(path);
        } catch (RuntimeException e) {
            return null;
        }
    }

    public static String fieldText(Response response, String path) {
        Object value = field(response, path);
        return value == null ? null : String.valueOf(value);
    }

    public static List<Object> list(Response response, String path) {
        if (text(response).isBlank()) {
            return List.of();
        }
        try {
            List<Object> values = response.jsonPath().getList(path);
            return values == null ? List.of() : values;
        } catch (RuntimeException e) {
            return List.of();
        }
    }

    public static String extractId(Response response) {
        Object id = field(response, "id");
        if (id != null && !(id instanceof List)) {
            return String.valueOf(id);
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }

    public static boolean isSuccess(int status) {
        return status >= 200 && status < 300;
    }

    public static boolean isClientError(int status) {
        return status >= 400 && status < 500;
    }
}
