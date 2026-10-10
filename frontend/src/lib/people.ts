import type { Person } from '../api/client'

/** What people see of a person: the display name, else the name they sign in with. */
export function personName(person: Pick<Person, 'name' | 'display_name'>): string {
  return person.display_name || person.name
}

/** The circle of a person, as `Avatar` draws it: it wants a picture field that the list of people does not carry. */
export function asAvatarPerson(person: Person): Person & { avatar: null } {
  return { ...person, avatar: null }
}
