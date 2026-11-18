package td.minisut;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/items")
public class ItemController {

    private final AtomicInteger nextId = new AtomicInteger(3);

    private final List<Map<String, Object>> items = new CopyOnWriteArrayList<>(List.of(
        Map.<String, Object>of("id", 1, "name", "apple"),
        Map.<String, Object>of("id", 2, "name", "banana")));

    @GetMapping
    public List<Map<String, Object>> list() {
        return new ArrayList<>(items);
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(@RequestBody Map<String, String> body) {
        String name = body.get("name");
        if (name == null || name.isBlank()) {
            return ResponseEntity.badRequest().build();
        }
        Map<String, Object> item = Map.of("id", nextId.getAndIncrement(), "name", name);
        items.add(item);
        return ResponseEntity.status(HttpStatus.CREATED).body(item);
    }
}
