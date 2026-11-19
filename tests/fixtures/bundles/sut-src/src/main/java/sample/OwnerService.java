package org.example.sample;

import java.util.List;

public class OwnerService {
	private final OwnerRepository ownerRepository;
	public OwnerService(OwnerRepository ownerRepository) {
		this.ownerRepository = ownerRepository;
	}
	public List<Owner> findByLastName(String lastName) {
		return this.ownerRepository.findByLastNameStartingWith(lastName);
	}
}
