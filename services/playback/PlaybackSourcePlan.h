#pragma once
#include "ApiClient.h"
#include "MembershipService.h"
#include <QJsonObject>
#include <QList>

namespace EchoMusic
{
/// Immutable source-selection plan built from the Rust domain model.
/// Each candidate still requires native authorization; unknown provider rights
/// are never inferred from display metadata.
struct PlaybackSourceCandidate
{
    QString hash;
    ApiClient::PlaybackQuality quality = ApiClient::PlaybackQuality::Automatic;
    ApiClient::SoundEffect effect = ApiClient::SoundEffect::None;
    QString originPage;
    QString resolvedQuality;
};
class PlaybackSourcePlan
{
public:
    /// Explicit zero-cost legacy file facts, not account authorization or a
    /// substitute for membership checks on Viper qualities.
    static bool isFreeLegacyFile(const QJsonObject &file);
    static QList<PlaybackSourceCandidate>
    catalog(const QString &hash, const QJsonObject &privileges,
            ApiClient::PlaybackQuality preferred, ApiClient::SoundEffect effect, bool compatibility,
            bool viperEnabled, MembershipFacts membership = {});
    static QString qualityKey(ApiClient::PlaybackQuality quality);
    /// Match the returned file, especially for original-hash Automatic requests.
    /// An empty result means the actual quality is unknown, never the preference.
    static QString sourceQuality(const QJsonObject &source,
                                 const PlaybackSourceCandidate &candidate,
                                 const QJsonObject &privileges);
    static QString qualityAccessReason(ApiClient::PlaybackQuality quality,
                                       MembershipFacts membership, bool viperEnabled,
                                       const QJsonObject &privileges = {});
    static QJsonObject qualityVariant(ApiClient::PlaybackQuality quality,
                                      const QJsonObject &privileges);
};
} // namespace EchoMusic
