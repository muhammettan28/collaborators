import { User } from '@/features/auth';
import { Doc } from '@/features/docs/doc-management';

export enum WorkspaceRole {
  MEMBER = 'member',
  ADMIN = 'administrator',
  OWNER = 'owner',
}

export type PublishingPolicy = 'space_admins' | 'workspace_admins';

/** Who can find a workspace in "Discover workspaces" and ask to join */
export type WorkspaceVisibility = 'public' | 'platform' | 'hidden';

/** A Google Workspace ("google:<domain>") or Microsoft tenant ("microsoft:<id>") */
export interface Organization {
  id: string;
  name: string;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  publishing_policy: PublishingPolicy;
  visibility: WorkspaceVisibility;
  /** Verified emails at these domains join when signing in (admins only) */
  join_domains: string[];
  /** The organisation group those people join too */
  join_group: string | null;
  /** People of these organisations join when signing in (admins only) */
  join_organizations: Organization[];
  /** The organisations the admin signed in with, which they may add */
  join_organization_choices: Organization[];
  /** People joining by link, domain or organisation wait for an admin's yes */
  join_approval: boolean;
  /** How many wait for that (admins only) */
  pending_join_requests: number;
  /** The secret of the join link, for admins; none when it is off */
  join_token: string | null;
  user_role: WorkspaceRole | null;
  abilities: {
    destroy: boolean;
    manage_accesses: boolean;
    /** Any member creates teams; administrators also organizations */
    create_groups: boolean;
    manage_groups: boolean;
    partial_update: boolean;
    retrieve: boolean;
    spaces_create: boolean;
    update: boolean;
  };
  created_at: string;
  updated_at: string;
}

export interface WorkspaceAccess {
  id: string;
  user: User;
  role: WorkspaceRole;
  created_at: string;
}

export enum GroupKind {
  TEAM = 'team',
  ORGANIZATION = 'organization',
}

export interface Group {
  id: string;
  /** A user group belongs to a workspace, or to a page or a space */
  workspace: string | null;
  /** The page or space of a user group for mentions only */
  document: string | null;
  name: string;
  kind: GroupKind;
  description: string;
  team: string;
  nb_members: number;
  /** Who created it; they manage it like the workspace's administrators */
  created_by: { id: string; full_name: string } | null;
  abilities: {
    destroy: boolean;
    /** Appoint the group's managers */
    manage_managers: boolean;
    manage_members: boolean;
    partial_update: boolean;
    retrieve: boolean;
    update: boolean;
  };
  created_at: string;
}

export interface GroupMembership {
  id: string;
  user: User;
  is_manager: boolean;
  created_at: string;
}

export interface LinkedWorkspace {
  id: string;
  name: string;
  slug: string;
  is_home: boolean;
}

export type Space = Doc & {
  linked_workspaces: LinkedWorkspace[];
  /** In a workspace's list: the role all its members have on it, if any */
  members_role?: string | null;
};

export enum SpaceVisibility {
  PUBLIC = 'public',
  WORKSPACE = 'workspace',
  INVITED = 'invited',
}

/** A group, or all members of a workspace, that a role can be granted to. */
/** Where a user group belongs: a workspace, or a page or a space */
export interface TeamPlace {
  kind: 'workspace' | 'page' | 'space';
  id: string;
  name: string;
}

export interface GrantableTeam {
  team: string;
  label: string;
  kind: 'workspace' | GroupKind;
  /** None for the user groups of a page or a space */
  workspace: { id: string; name: string } | null;
  place: TeamPlace;
  member_count: number;
}

export interface WorkspaceGrant {
  team: string;
  label: string;
  role: string;
}
