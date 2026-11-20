package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class PetManagementSteps {

    private Response response;
    private String ownerId;
    private Object typeId;
    private Object typeName;
    private String petId;
    private String petName;

    private Map<String, Object> petBody(String name) {
        Map<String, Object> body = new LinkedHashMap<>();
        if (name != null) {
            body.put("name", name);
        }
        body.put("birthDate", ApiSupport.pastDate(ApiSupport.randomInt(100, 2000)));
        body.put("ownerId", ownerId);
        if (typeId != null) {
            body.put("typeId", typeId);
        } else if (typeName != null) {
            body.put("type", typeName);
        }
        return body;
    }

    private Response readPet() {
        assertThat(petId).as("id of the registered pet").isNotBlank();
        return Harness.authed().get("/api/pets/" + petId);
    }

    @When("the pet client lists the pet types")
    public void listsPetTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet type list is a JSON array")
    public void typeListIsArray() {
        assertThat(ApiSupport.text(response).trim()).startsWith("[");
    }

    @Given("a pet owner and a pet type are available for the pet client")
    public void ownerAndTypeAvailable() {
        Response owner = Harness.authed().contentType("application/json").body(ApiSupport.randomOwner())
                .post("/api/owners");
        assertThat(owner.statusCode()).as("owner creation status, body: %s", ApiSupport.text(owner)).isIn(200, 201);
        ownerId = ApiSupport.extractId(owner);
        assertThat(ownerId).as("id of the pet owner").isNotBlank();
        Response types = Harness.authed().get("/api/pets/types");
        assertThat(types.statusCode()).isEqualTo(200);
        List<Object> all = ApiSupport.list(types, "$");
        assertThat(all).as("available pet types").isNotEmpty();
        Object first = all.get(0);
        if (first instanceof Map) {
            Map<?, ?> type = (Map<?, ?>) first;
            typeId = type.get("id");
            typeName = type.get("name");
        } else {
            typeName = first;
        }
    }

    @When("the pet client registers a pet with a unique name")
    public void registersPet() {
        petName = ApiSupport.uniqueName("Rex");
        response = Harness.authed().contentType("application/json").body(petBody(petName)).post("/api/pets");
        if (ApiSupport.isSuccess(response.statusCode())) {
            petId = ApiSupport.extractId(response);
        }
    }

    @When("the pet client renames the registered pet")
    public void renamesPet() {
        assertThat(petId).as("id of the registered pet").isNotBlank();
        petName = ApiSupport.uniqueName("Max");
        response = Harness.authed().contentType("application/json").body(petBody(petName)).put("/api/pets/" + petId);
    }

    @When("the pet client registers a pet without a name")
    public void registersPetWithoutName() {
        response = Harness.authed().contentType("application/json").body(petBody(null)).post("/api/pets");
    }

    @When("the pet client reads pet id {int}")
    public void readsPetById(int id) {
        response = Harness.authed().get("/api/pets/" + id);
    }

    @Then("reading the registered pet shows its unique name")
    public void readingShowsUniqueName() {
        Response read = readPet();
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(ApiSupport.fieldText(read, "name")).isEqualTo(petName);
    }

    @Then("reading the registered pet shows its new name")
    public void readingShowsNewName() {
        Response read = readPet();
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(ApiSupport.fieldText(read, "name")).isEqualTo(petName);
    }

    @Then("the pet response status is {int}")
    public void petStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }

    @Then("the pet response is successful")
    public void petResponseSuccessful() {
        assertThat(ApiSupport.isSuccess(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }

    @Then("the pet response is a client error")
    public void petResponseClientError() {
        assertThat(ApiSupport.isClientError(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }
}
