import { Button, Checkbox, Input } from '@gouvfr-lasuite/ui-components';
import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Loading, Text } from '@/components';

import {
  PlatformNumberSettingName,
  PlatformSetting,
  PlatformSettingName,
  usePlatformSettings,
  useUpdatePlatformSettings,
} from './api';

const rowCss = css`
  border-top: 1px solid var(--c--contextuals--border--surface--primary);
  padding-top: var(--c--globals--spacings--xs);
`;

/** A setting that is a number, saved when changed. */
const NumberSetting = ({
  name,
  setting,
  label,
  help,
  min,
  max,
}: {
  name: PlatformNumberSettingName;
  setting: PlatformSetting<number>;
  label: string;
  help: string;
  min: number;
  max: number;
}) => {
  const { t } = useTranslation();
  const update = useUpdatePlatformSettings();
  const [value, setValue] = useState(String(setting.value));
  const number = Number(value);
  const valid = Number.isInteger(number) && number >= min && number <= max;

  return (
    <Box $gap="4xs" $css={rowCss}>
      <Box
        as="form"
        $direction="row"
        $gap="xs"
        $align="flex-end"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (valid) {
            update.mutate({ [name]: number });
          }
        }}
      >
        <Box $css="max-width: 260px;">
          <Input
            type="number"
            label={label}
            value={value}
            min={min}
            max={max}
            onChange={(event) => setValue(event.target.value)}
          />
        </Box>
        <Button
          size="small"
          type="submit"
          disabled={!valid || number === setting.value || update.isPending}
        >
          {t('Save', { description: 'Button saving a platform setting' })}
        </Button>
      </Box>
      <Text $size="xs" $variation="secondary">
        {help}
      </Text>
      <Box $direction="row" $align="center" $gap="xs">
        <Text $size="xs" $variation="secondary">
          {t('The server’s own: {{value}}', {
            description: 'The value of a setting set on the server',
            value: setting.server_default,
          })}
        </Text>
        {setting.set_here && (
          <Button
            size="small"
            variant="tertiary"
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                { [name]: null },
                {
                  onSuccess: (data) => setValue(String(data[name].value)),
                },
              )
            }
          >
            {t('Follow the server’s own', {
              description: 'Button forgetting a platform setting',
            })}
          </Button>
        )}
      </Box>
    </Box>
  );
};

/** "Settings", for platform owners: what the platform does for everyone. */
export const PlatformSettings = () => {
  const { t } = useTranslation();
  const { data, isLoading } = usePlatformSettings();
  const update = useUpdatePlatformSettings();
  const texts: Record<PlatformSettingName, { label: string; help: string }> = {
    signup_approval: {
      label: t('New registrations wait for approval', {
        description: 'Platform setting',
      }),
      help: t(
        'Someone signing in for the first time waits until a manager lets them in. People invited by email never wait.',
        { description: 'Explanation of the registration approval setting' },
      ),
    },
    email_invitations: {
      label: t('Invitations by email', { description: 'Platform setting' }),
      help: t(
        'Workspaces, spaces and pages can invite people by email, who sign up from the invitation.',
        { description: 'Explanation of the email invitations setting' },
      ),
    },
  };
  const onOff = (value: boolean) =>
    value
      ? t('on', { description: 'A setting turned on' })
      : t('off', { description: 'A setting turned off' });

  return (
    <Box $gap="sm" data-testid="platform-settings">
      <Text $variation="secondary">
        {t(
          'These apply to everyone on the platform. A setting you never changed follows the server’s own. Every change is logged.',
          { description: 'Introduction of the platform settings tab' },
        )}
      </Text>
      {isLoading && <Loading />}
      {data &&
        (Object.keys(texts) as PlatformSettingName[]).map((name) => (
          <Box key={name} $gap="4xs" $css={rowCss}>
            <Checkbox
              label={texts[name].label}
              checked={data[name].value}
              disabled={update.isPending}
              onChange={(event) =>
                update.mutate({ [name]: event.target.checked })
              }
            />
            <Text $size="xs" $variation="secondary">
              {texts[name].help}
            </Text>
            <Box $direction="row" $align="center" $gap="xs">
              <Text $size="xs" $variation="secondary">
                {t('The server’s own: {{value}}', {
                  description: 'The value of a setting set on the server',
                  value: onOff(data[name].server_default),
                })}
              </Text>
              {data[name].set_here && (
                <Button
                  size="small"
                  variant="tertiary"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ [name]: null })}
                >
                  {t('Follow the server’s own', {
                    description: 'Button forgetting a platform setting',
                  })}
                </Button>
              )}
            </Box>
          </Box>
        ))}
      {data?.presentation_storage_mb && (
        <NumberSetting
          name="presentation_storage_mb"
          setting={data.presentation_storage_mb}
          min={0}
          max={100000}
          label={t('Storage for presentations, per person (MB)', {
            description: 'Platform setting',
          })}
          help={t(
            'What each person may store of HTML presentations uploaded to pages, every version they uploaded included. Presentations shown from a link elsewhere take no room.',
            { description: 'Explanation of the presentation storage setting' },
          )}
        />
      )}
      {data?.presentation_versions && (
        <NumberSetting
          name="presentation_versions"
          setting={data.presentation_versions}
          min={1}
          max={100}
          label={t('Versions kept of each presentation', {
            description: 'Platform setting',
          })}
          help={t(
            'When a presentation is replaced, its earlier versions are kept up to this number, then the oldest go.',
            { description: 'Explanation of the presentation versions setting' },
          )}
        />
      )}
    </Box>
  );
};
