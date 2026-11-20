Feature: Veterinarian directory
  Veterinarians can be listed and read individually.

  Scenario: List all veterinarians
    When the vet directory is listed
    Then the vet directory listing is successful

  Scenario: Read a veterinarian taken from the directory
    Given the vet directory has been listed
    When the first listed vet is requested by id
    Then the vet details are returned for that id when the directory is not empty
