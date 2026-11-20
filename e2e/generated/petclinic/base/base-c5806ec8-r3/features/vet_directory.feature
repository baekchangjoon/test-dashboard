Feature: Veterinarian directory

  Scenario: List veterinarians
    When the veterinarian directory is requested
    Then the veterinarian directory responds successfully

  Scenario: Fetch a veterinarian from the directory by id
    Given the veterinarian directory has been loaded
    When the first listed veterinarian is fetched by id
    Then the veterinarian detail matches the listed veterinarian
